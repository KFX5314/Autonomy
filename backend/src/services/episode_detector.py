"""
Episode detection engine.

Two-stage pipeline:
  1. Rule-based matching (fast, deterministic) — trigger phrases and regex
     patterns. Runs ONLY over [PACIENTE]-tagged text when diarization is
     available, so caregivers speaking trigger words don't fire the alert.
  2. LLM-based analysis — contextual reasoning. A single call produces the
     classification AND (when it's an episode) the calming spoken reply,
     avoiding a second round-trip.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm import get_llm_provider

logger = logging.getLogger(__name__)


@dataclass
class EpisodeResult:
    is_episode: bool
    severity: int  # 0-5
    reason: str
    llm_response: str | None = None


_PACIENTE_LINE = re.compile(r"\[PACIENTE\]\s*(.+?)(?=\s*\[(?:PACIENTE|OTRO)\]|\s*$)", re.DOTALL)


def _extract_patient_text(transcript: str) -> str:
    if not transcript:
        return ""
    if "[PACIENTE]" not in transcript and "[OTRO]" not in transcript:
        return transcript
    return " ".join(m.group(1).strip() for m in _PACIENTE_LINE.finditer(transcript)).strip()


def _build_reply_system_prompt(context: dict) -> str:
    profile = context.get("static_profile", {})
    name = profile.get("preferred_name", "el paciente")
    address = profile.get("current_address", "su domicilio")
    caregivers = ", ".join(profile.get("caregiver_names", []))
    medical_notes = profile.get("medical_notes", [])
    style = context.get("assistant_style", {})
    tone = style.get("tone", "calmado")
    max_words = style.get("max_words", 40)

    prompt = (
        f"Eres un asistente para una persona con demencia llamada {name}. "
        f"Responde SIEMPRE en español, con frases cortas, tono {tone}, máximo {max_words} palabras. "
        f"No inventes datos. No des consejos médicos. No menciones que eres una IA.\n"
        f"Contexto: {name} está en {address}. "
        f"Cuidadores: {caregivers}.\n"
    )
    if medical_notes:
        notes_str = "; ".join(medical_notes)
        prompt += f"Notas médicas importantes: {notes_str}.\n"
    prompt += "Si la persona está confundida, oriéntala con calma y dile que su cuidador va a ser avisado."
    return prompt


def _build_profile_block(context: dict) -> str:
    profile = context.get("static_profile", {})
    name = profile.get("preferred_name", "el paciente")
    address = profile.get("current_address", "su domicilio")
    caregivers = ", ".join(profile.get("caregiver_names", [])) or "sin cuidadores registrados"
    medical_notes = profile.get("medical_notes", [])
    style = context.get("assistant_style", {})
    tone = style.get("tone", "calmado")
    max_words = style.get("max_words", 40)

    lines = [
        f"Paciente: {name}.",
        f"Domicilio habitual: {address}.",
        f"Cuidadores: {caregivers}.",
    ]
    if medical_notes:
        lines.append("Notas médicas relevantes:")
        for n in medical_notes:
            lines.append(f"  - {n}")
    lines.append(f"Estilo de respuesta si hay que hablarle: tono {tone}, máximo {max_words} palabras.")
    return "\n".join(lines)


def _build_analysis_prompt(context: dict, transcript: str, short_term_memory: str = "") -> str:
    triggers = context.get("trigger_phrases", [])
    rules = context.get("risk_rules", [])

    trigger_lines = []
    for t in triggers:
        if isinstance(t, str):
            trigger_lines.append(f'- "{t}" (severidad 3)')
        else:
            trigger_lines.append(f'- "{t["text"]}" (severidad {t.get("severity", 3)})')
    trigger_list = "\n".join(trigger_lines) or "- (ninguna)"

    rule_lines = []
    for r in rules:
        if isinstance(r, str):
            rule_lines.append(f'- patrón: "{r}" → riesgo: medio')
        else:
            rule_lines.append(f'- patrón: "{r["pattern"]}" → riesgo: {r.get("risk", "desconocido")}')
    rule_list = "\n".join(rule_lines) or "- (ninguna)"

    stm_section = ""
    if short_term_memory:
        stm_section = (
            "\nContexto reciente del paciente (últimos minutos, sólo frases del paciente):\n"
            f"{short_term_memory}\n"
        )

    return (
        f"Analiza la siguiente transcripción y decide si el paciente está teniendo un episodio "
        f"de desorientación, necesita ayuda, o está diciendo algo peligroso según su historial médico.\n\n"
        f"La transcripción puede contener etiquetas [PACIENTE] y [OTRO]. "
        f"Sólo las frases de [PACIENTE] son del paciente; las de [OTRO] son de acompañantes y dan contexto "
        f"pero NUNCA activan un episodio por sí solas.\n\n"
        f"--- Perfil del paciente ---\n"
        f"{_build_profile_block(context)}\n\n"
        f"--- Frases gatillo conocidas ---\n{trigger_list}\n\n"
        f"--- Reglas de riesgo ---\n{rule_list}\n"
        f"{stm_section}\n"
        f"--- Transcripción a evaluar ---\n\"{transcript}\"\n\n"
        f"Responde SOLO con un JSON válido con esta forma exacta:\n"
        f'{{"episode": true/false, "severity": 0-5, "reason": "explicación breve en español", '
        f'"reply": "lo que le dirías al paciente si episode=true, o null en caso contrario"}}\n'
        f"Si episode=false, \"reply\" debe ser null. Si episode=true, \"reply\" debe ser una frase corta, "
        f"en el tono indicado, que orientará al paciente con calma."
    )


def _parse_llm_json(raw: str) -> dict | None:
    if not raw:
        return None
    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        return None
    json_str = json_match.group()
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*]", "]", json_str)
    json_str = re.sub(r"//.*$", "", json_str, flags=re.MULTILINE)
    json_str = re.sub(r"(?<=[{\[,:\s])'", '"', json_str)
    json_str = re.sub(r"'(?=[}\],:\s])", '"', json_str)
    json_str = re.sub(r"(?<=[{,])\s*(\w+)\s*:", r' "\1":', json_str)
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        ep_match = re.search(r'episode["\']?\s*:\s*(true|false)', raw, re.IGNORECASE)
        sev_match = re.search(r'severity["\']?\s*:\s*(\d)', raw)
        reason_match = re.search(r'reason["\']?\s*:\s*["\'](.+?)["\']', raw, re.DOTALL)
        reply_match = re.search(r'reply["\']?\s*:\s*(?:null|"(.+?)")', raw, re.DOTALL | re.IGNORECASE)
        if not any([ep_match, sev_match, reason_match]):
            return None
        return {
            "episode": ep_match.group(1).lower() == "true" if ep_match else False,
            "severity": int(sev_match.group(1)) if sev_match else 0,
            "reason": reason_match.group(1) if reason_match else "Análisis LLM",
            "reply": reply_match.group(1) if (reply_match and reply_match.group(1)) else None,
        }


class EpisodeDetector:
    """Detects episodes using a combination of rules and LLM analysis."""

    def __init__(self, context_json: dict):
        self.context = context_json

    def _rule_based_check(self, patient_text: str) -> EpisodeResult | None:
        text_lower = (patient_text or "").lower().strip()
        if not text_lower:
            return None

        for trigger in self.context.get("trigger_phrases", []):
            if isinstance(trigger, str):
                phrase = trigger.lower()
                severity = 3
                display = trigger
            else:
                phrase = trigger.get("text", "").lower()
                severity = trigger.get("severity", 3)
                display = trigger.get("text", phrase)
            if phrase and phrase in text_lower:
                return EpisodeResult(
                    is_episode=True,
                    severity=severity,
                    reason=f'Frase gatillo detectada: "{display}"',
                )

        for rule in self.context.get("risk_rules", []):
            if isinstance(rule, str):
                pattern = rule
                risk_label = rule
            else:
                pattern = rule.get("pattern", "")
                risk_label = rule.get("risk", pattern)
            if pattern and re.search(pattern, text_lower):
                return EpisodeResult(
                    is_episode=True,
                    severity=4,
                    reason=f"Regla de riesgo activada: {risk_label}",
                )

        return None

    async def analyze(
        self,
        transcript: str,
        short_term_memory: str = "",
        use_llm: bool = True,
    ) -> EpisodeResult:
        patient_text = _extract_patient_text(transcript)
        rule_result = self._rule_based_check(patient_text)

        if rule_result is not None:
            if use_llm:
                try:
                    llm = get_llm_provider()
                    system = _build_reply_system_prompt(self.context)
                    response = await llm.generate(system, transcript)
                    rule_result.llm_response = response
                except Exception as e:
                    logger.warning(f"LLM reply generation failed, returning rule-only result: {e}")
            return rule_result

        if not use_llm:
            return EpisodeResult(is_episode=False, severity=0, reason="Sin coincidencias")

        try:
            llm = get_llm_provider()
            analysis_prompt = _build_analysis_prompt(self.context, transcript, short_term_memory)
            raw = await llm.generate(
                "Eres un sistema de detección de episodios de demencia. Responde SOLO con JSON válido.",
                analysis_prompt,
            )
            parsed = _parse_llm_json(raw)
            if parsed is None:
                logger.warning("LLM returned unparseable response; treating as no-episode.")
                return EpisodeResult(is_episode=False, severity=0, reason="Respuesta LLM inválida")

            is_episode = bool(parsed.get("episode", False))
            severity = int(parsed.get("severity") or 0)
            reason = (parsed.get("reason") or "Análisis LLM").strip()
            reply = parsed.get("reply")
            if isinstance(reply, str):
                reply = reply.strip() or None
            else:
                reply = None

            return EpisodeResult(
                is_episode=is_episode,
                severity=severity,
                reason=reason,
                llm_response=reply if is_episode else None,
            )
        except Exception as e:
            logger.warning(f"LLM analysis failed: {e}")
            return EpisodeResult(is_episode=False, severity=0, reason="Análisis no disponible")
