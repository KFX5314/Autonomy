"""
Wake-word assistant QA service.

When the patient says a configured wake word (for example "asistente" or
"ayudame"), the audio pipeline diverts the flow here instead of the episode
detector. The answer is spoken back by the patient app via expo-speech. This is
not the alert/episode path: no Alert row is persisted here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..config import config
from ..models.journal import JournalEntry
from ..models.patient import Patient, PatientContext
from .llm import get_llm_provider

logger = logging.getLogger(__name__)


def _build_system_prompt(context: dict) -> str:
    profile = context.get("static_profile", {})
    name = profile.get("preferred_name", "el paciente")
    style = context.get("assistant_style", {})
    tone = style.get("tone", "calmado")
    max_words = style.get("max_words", 40)

    return (
        f"Eres un asistente personal para {name}, una persona mayor. "
        f"Responde SIEMPRE en espanol (es-ES), frases cortas, tono {tone}, "
        f"maximo {max_words} palabras. "
        "No inventes datos. Si no sabes algo, di que no lo sabes. "
        "No des consejos medicos: para cuestiones de salud, di que avisaras al cuidador. "
        "Responde directamente a la pregunta o peticion del paciente."
    )


def _build_user_prompt(
    context: dict,
    patient_text: str,
    journal_entries: list[JournalEntry],
    stm: str,
    full_transcript: str = "",
) -> str:
    profile = context.get("static_profile", {})
    name = profile.get("preferred_name", "el paciente")
    address = profile.get("current_address", "su domicilio")
    caregivers = ", ".join(profile.get("caregiver_names", [])) or "sin cuidadores registrados"
    medical_notes = profile.get("medical_notes", [])

    lines = [
        "Datos del paciente:",
        f"- Nombre: {name}",
        f"- Domicilio: {address}",
        f"- Cuidadores: {caregivers}",
    ]
    if medical_notes:
        lines.append("- Notas medicas:")
        for note in medical_notes:
            lines.append(f"    - {note}")

    if journal_entries:
        lines.append("")
        lines.append(f"Journal del paciente (ultimas {config.JOURNAL_RETENTION_HOURS} h):")
        for entry in journal_entries:
            when = entry.created_at.strftime("%H:%M") if entry.created_at else ""
            lines.append(f"- [{when}] {entry.summary_text}")

    if stm:
        lines.append("")
        lines.append("Memoria reciente ([PACIENTE], [PACIENTE?] y posibles respuestas [ASSISTANT] previas):")
        lines.append("[PACIENTE?] significa posible paciente con identificacion de voz dudosa.")
        lines.append(stm)

    if full_transcript:
        lines.append("")
        lines.append("Transcripcion completa del audio actual (incluye a todas las personas presentes):")
        lines.append(full_transcript)

    lines.append("")
    if patient_text:
        lines.append(f'Pregunta/peticion del paciente: "{patient_text}"')
    else:
        lines.append(
            "El paciente ha llamado al asistente. Usa la memoria reciente y "
            "el contexto de la conversacion para inferir que necesita y "
            "respondele directamente."
        )
    lines.append("Responde directamente al paciente, sin preambulos.")
    return "\n".join(lines)


async def answer_patient_query(
    patient: Patient,
    patient_text: str,
    stm: str,
    db: Session,
    full_transcript: str = "",
) -> dict:
    """Generate a short spoken answer for the patient.

    Returns {"reply_text": str | None}.
    """
    ctx = (
        db.query(PatientContext)
        .filter(PatientContext.patient_id == patient.id)
        .first()
    )
    context_data = ctx.context_json if ctx else {}

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=config.JOURNAL_RETENTION_HOURS)
    recent_entries = (
        db.query(JournalEntry)
        .filter(JournalEntry.patient_id == patient.id)
        .filter(JournalEntry.created_at >= cutoff)
        .order_by(JournalEntry.created_at.desc())
        .all()
    )
    # Chronological order reads more naturally in the prompt.
    recent_entries = list(reversed(recent_entries))

    system = _build_system_prompt(context_data)
    user_prompt = _build_user_prompt(
        context_data,
        patient_text,
        recent_entries,
        stm,
        full_transcript=full_transcript,
    )

    try:
        llm = get_llm_provider()
        reply = await llm.generate(system, user_prompt)
        reply = (reply or "").strip()
        if not reply:
            reply = "Lo siento, no he entendido. Puedes repetirlo?"
        return {"reply_text": reply}
    except Exception as exc:
        logger.warning(f"Assistant LLM failed: {exc}")
        return {"reply_text": "Lo siento, ahora no puedo responder. Ya aviso a tu cuidador."}
