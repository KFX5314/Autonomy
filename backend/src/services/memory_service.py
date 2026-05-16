"""
Memory layer.

- Short-term memory (STM): rolling window of recent utterances pulled from the
  transcripts table on demand and injected into LLM prompts. No extra storage.
- Long-term memory (LTM / journal): LLM-condensed summaries of the selected STM
  material, persisted in journal_entries. Generated in a FastAPI BackgroundTask
  so it never adds latency to the audio-chunk response.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy import and_, delete, or_
from sqlalchemy.orm import Session

from ..config import config
from ..database import SessionLocal
from ..models.journal import JournalEntry
from ..models.transcript import Transcript
from .llm import get_llm_provider

logger = logging.getLogger(__name__)


_TAG_NAME = r"PACIENTE\?|PACIENTE|OTRO|ASISTENTE"
_ANY_TAG = rf"(?:{_TAG_NAME})"
_MEMORY_LINE = re.compile(
    rf"\[({_TAG_NAME})\]\s*(.+?)(?=\s*\[{_ANY_TAG}\]|\s*$)",
    re.DOTALL,
)

_journal_in_flight: set[int] = set()
_journal_in_flight_lock = Lock()


@dataclass(frozen=True)
class _STMItem:
    transcript_id: int
    started_at: datetime
    tag: str
    text: str
    line: str


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _extract_memory_lines(
    transcript_text: str,
    include_assistant: bool = True,
    include_other: bool = False,
    include_uncertain_patient: bool = True,
) -> list[tuple[str, str]]:
    """Return tagged fragments that are relevant to the requested memory view.

    For transcripts without speaker tags (for example, before voice enrollment)
    the whole text is treated as patient-spoken.
    """
    if not transcript_text:
        return []
    if all(tag not in transcript_text for tag in ("[PACIENTE]", "[PACIENTE?]", "[OTRO]", "[ASISTENTE]")):
        text = transcript_text.strip()
        return [("PACIENTE", text)] if text else []

    allowed = {"PACIENTE"}
    if include_uncertain_patient:
        allowed.add("PACIENTE?")
    if include_assistant:
        allowed.add("ASISTENTE")
    if include_other:
        allowed.add("OTRO")

    lines: list[tuple[str, str]] = []
    for match in _MEMORY_LINE.finditer(transcript_text):
        tag = match.group(1)
        text = match.group(2).strip()
        if tag in allowed and text:
            lines.append((tag, text))
    return lines


def _get_short_term_items(
    patient_id: int,
    db: Session,
    now: datetime | None = None,
    window_minutes: int | None = None,
    max_utterances: int | None = None,
    max_chars: int | None = None,
    exclude_transcript_id: int | None = None,
    include_assistant: bool = True,
    include_other: bool = False,
    include_uncertain_patient: bool = True,
) -> list[_STMItem]:
    """Return the exact STM items selected after line and char caps.

    Items are returned oldest-first, matching the final LLM-readable STM text.
    """
    now = now or datetime.now(timezone.utc)
    window_minutes = window_minutes or config.STM_WINDOW_MINUTES
    max_utterances = max_utterances or config.STM_MAX_UTTERANCES
    max_chars = max_chars or config.STM_MAX_CHARS

    cutoff = _naive_utc(now) - timedelta(minutes=window_minutes)
    query = (
        db.query(Transcript)
        .filter(Transcript.patient_id == patient_id)
        .filter(Transcript.started_at >= cutoff)
    )
    if exclude_transcript_id is not None:
        query = query.filter(Transcript.id != exclude_transcript_id)

    batch_size = max(1, max_utterances * 4)
    max_rows_to_scan = max(batch_size, max_utterances * 12)

    items: list[_STMItem] = []
    rows_scanned = 0
    before_started_at: datetime | None = None
    before_id: int | None = None

    while len(items) < max_utterances and rows_scanned < max_rows_to_scan:
        page_query = query
        if before_started_at is not None and before_id is not None:
            page_query = page_query.filter(
                or_(
                    Transcript.started_at < before_started_at,
                    and_(
                        Transcript.started_at == before_started_at,
                        Transcript.id < before_id,
                    ),
                )
            )

        rows = (
            page_query
            .order_by(Transcript.started_at.desc(), Transcript.id.desc())
            .limit(min(batch_size, max_rows_to_scan - rows_scanned))
            .all()
        )
        if not rows:
            break

        rows_scanned += len(rows)
        last_row = rows[-1]
        before_started_at = last_row.started_at
        before_id = last_row.id

        for row in rows:
            ts = row.started_at.strftime("%H:%M")
            fragments = _extract_memory_lines(
                row.transcript_text,
                include_assistant=include_assistant,
                include_other=include_other,
                include_uncertain_patient=include_uncertain_patient,
            )
            # Rows are scanned newest-first. Within a transcript, regex
            # fragments are chronological, so reverse them while collecting
            # and reverse the final item list back to oldest-first below.
            for tag, text in reversed(fragments):
                line = f"[{ts}] [{tag}] {text}"
                items.append(_STMItem(row.id, row.started_at, tag, text, line))
                if len(items) >= max_utterances:
                    break
            if len(items) >= max_utterances:
                break

        if len(rows) < batch_size:
            break

    if not items:
        return []

    items.reverse()

    total = sum(len(item.line) + 1 for item in items)
    while total > max_chars and len(items) > 1:
        dropped = items.pop(0)
        total -= len(dropped.line) + 1

    return items


def get_short_term(
    patient_id: int,
    db: Session,
    now: datetime | None = None,
    window_minutes: int | None = None,
    max_utterances: int | None = None,
    max_chars: int | None = None,
    exclude_transcript_id: int | None = None,
    include_assistant: bool = True,
    include_other: bool = False,
) -> str:
    """Build the STM string for a patient, oldest-first.

    Format: one line per utterance:
        [HH:MM] [TAG] text
    """
    items = _get_short_term_items(
        patient_id,
        db,
        now=now,
        window_minutes=window_minutes,
        max_utterances=max_utterances,
        max_chars=max_chars,
        exclude_transcript_id=exclude_transcript_id,
        include_assistant=include_assistant,
        include_other=include_other,
    )
    return "\n".join(item.line for item in items)


def _journal_summary_items(
    patient_id: int,
    db: Session,
    now: datetime | None = None,
) -> list[_STMItem]:
    return _get_short_term_items(
        patient_id,
        db,
        now=now,
        include_assistant=True,
        include_other=True,
        include_uncertain_patient=True,
    )


def _journal_has_patient_or_assistant_material(items: list[_STMItem]) -> bool:
    return any(item.tag in {"PACIENTE", "PACIENTE?", "ASISTENTE"} for item in items)


def _journal_items_have_new_coverage(patient_id: int, db: Session, items: list[_STMItem]) -> bool:
    if len(items) < config.JOURNAL_MIN_UTTERANCES:
        return False
    if not _journal_has_patient_or_assistant_material(items):
        return False

    latest_covers_end = (
        db.query(JournalEntry.covers_end)
        .filter(JournalEntry.patient_id == patient_id)
        .order_by(JournalEntry.covers_end.desc())
        .limit(1)
        .scalar()
    )
    if latest_covers_end is None:
        return True

    latest_covers_end = _naive_utc(latest_covers_end)
    return all(_naive_utc(item.started_at) > latest_covers_end for item in items)


def should_schedule_journal(
    patient_id: int,
    db: Session | None = None,
    now: datetime | None = None,
) -> bool:
    """Return True when the selected STM has fully turned over.

    The check is persistent: it compares current selected STM item timestamps
    with the latest journal coverage instead of a process-local timer.
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        items = _journal_summary_items(patient_id, db, now=now)
        if not _journal_items_have_new_coverage(patient_id, db, items):
            return False

        with _journal_in_flight_lock:
            if patient_id in _journal_in_flight:
                return False
            _journal_in_flight.add(patient_id)
        return True
    except Exception as exc:
        logger.warning(f"[journal] patient={patient_id}: schedule check failed: {exc}")
        return False
    finally:
        if owns_session:
            db.close()


def _release_journal_guard(patient_id: int) -> None:
    with _journal_in_flight_lock:
        _journal_in_flight.discard(patient_id)


def _trim_summary(summary: str) -> str:
    max_chars = config.JOURNAL_ENTRY_MAX_CHARS
    if len(summary) <= max_chars:
        return summary
    if max_chars <= 3:
        return summary[:max_chars]
    return summary[: max_chars - 3].rstrip() + "..."


async def summarize_and_append(
    patient_id: int,
    db: Session | None = None,
    now: datetime | None = None,
) -> None:
    """Background task: condense the current selected STM into one journal entry.

    Silently no-ops when there is no useful material or the current STM still
    overlaps the latest journal coverage.
    """
    owns_session = db is None
    db = db or SessionLocal()
    try:
        now = now or datetime.now(timezone.utc)
        items = _journal_summary_items(patient_id, db, now=now)
        if not items:
            logger.debug(f"[journal] patient={patient_id}: STM empty, skipping.")
            return
        if len(items) < config.JOURNAL_MIN_UTTERANCES:
            logger.debug(f"[journal] patient={patient_id}: STM too small ({len(items)} lines), skipping.")
            return
        if not _journal_has_patient_or_assistant_material(items):
            logger.debug(f"[journal] patient={patient_id}: STM only has [OTRO] material, skipping.")
            return
        if not _journal_items_have_new_coverage(patient_id, db, items):
            logger.debug(f"[journal] patient={patient_id}: STM still overlaps last journal entry, skipping.")
            return

        stm = "\n".join(item.line for item in items)
        system = (
            "Eres un asistente que escribe un diario breve para el cuidador de una persona con demencia. "
            "Resume solo actividad del paciente o respuestas del asistente, en tercera persona, de forma neutral "
            "y factual, en 1 o 2 frases cortas. Usa las lineas [OTRO] solo como contexto; no las atribuyas "
            "al paciente, al cuidador ni a ningun rol concreto si la etiqueta no lo dice. "
            "Responde SOLO con el resumen, sin comillas ni prefijos."
        )
        user_msg = (
            "Transcripciones recientes con hora y etiqueta de hablante:\n"
            "- [PACIENTE] es el paciente identificado.\n"
            "- [PACIENTE?] es posible paciente con identificacion de voz dudosa; no lo presentes como hecho seguro sin contexto.\n"
            "- [ASISTENTE] son respuestas habladas del sistema.\n"
            "- [OTRO] son otras personas o sonido transcrito del entorno; usalo solo como contexto y no infieras que es cuidador, familiar o paciente.\n\n"
            f"{stm}\n\n"
            "Escribe una entrada de diario."
        )
        llm = get_llm_provider()
        raw = await llm.generate(system, user_msg)
        summary = (raw or "").strip().strip('"').strip("'")
        if not summary:
            logger.debug(f"[journal] patient={patient_id}: LLM returned empty summary.")
            return
        summary = _trim_summary(summary)

        entry = JournalEntry(
            patient_id=patient_id,
            covers_start=_naive_utc(items[0].started_at),
            covers_end=_naive_utc(items[-1].started_at),
            summary_text=summary,
        )
        db.add(entry)
        db.flush()

        retention_cutoff = now - timedelta(hours=config.JOURNAL_RETENTION_HOURS)
        db.execute(
            delete(JournalEntry)
            .where(JournalEntry.patient_id == patient_id)
            .where(JournalEntry.created_at < _naive_utc(retention_cutoff))
        )

        total = db.query(JournalEntry).filter(JournalEntry.patient_id == patient_id).count()
        if total > config.JOURNAL_MAX_ENTRIES:
            excess = total - config.JOURNAL_MAX_ENTRIES
            oldest = (
                db.query(JournalEntry)
                .filter(JournalEntry.patient_id == patient_id)
                .order_by(JournalEntry.created_at.asc())
                .limit(excess)
                .all()
            )
            for entry_to_delete in oldest:
                db.delete(entry_to_delete)

        tx_cutoff = now - timedelta(days=config.TRANSCRIPT_RETENTION_DAYS)
        db.execute(
            delete(Transcript)
            .where(Transcript.patient_id == patient_id)
            .where(Transcript.created_at < _naive_utc(tx_cutoff))
        )
        tx_total = db.query(Transcript).filter(Transcript.patient_id == patient_id).count()
        if tx_total > config.TRANSCRIPT_MAX_ROWS:
            tx_excess = tx_total - config.TRANSCRIPT_MAX_ROWS
            tx_oldest = (
                db.query(Transcript)
                .filter(Transcript.patient_id == patient_id)
                .order_by(Transcript.created_at.asc())
                .limit(tx_excess)
                .all()
            )
            for transcript in tx_oldest:
                db.delete(transcript)

        db.commit()
        logger.info(f"[journal] patient={patient_id}: stored entry '{summary[:80]}...'")
    except Exception as exc:
        db.rollback()
        logger.warning(f"[journal] patient={patient_id}: summarization failed: {exc}")
    finally:
        _release_journal_guard(patient_id)
        if owns_session:
            db.close()
