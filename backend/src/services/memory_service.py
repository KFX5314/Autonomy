"""
Memory layer.

- Short-term memory (STM): rolling window of recent utterances,
  pulled from the `transcripts` table on demand and injected into the LLM
  analysis prompt. No new storage.
  - get_short_term(): returns [PACIENTE]-only lines (for episode detection).
  - get_recent_conversation(): returns ALL speakers with tags (for the
    assistant service, so the LLM has full conversational context).
- Long-term memory (LTM / journal): LLM-condensed 1-2 sentence summaries of
  recent conversation, persisted in `journal_entries`. Generated in a FastAPI
  BackgroundTask so it never adds latency to the audio-chunk response.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from threading import Lock

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import config
from ..database import SessionLocal
from ..models.journal import JournalEntry
from ..models.transcript import Transcript
from .llm import get_llm_provider

logger = logging.getLogger(__name__)


# Matches "[PACIENTE] text until next tag or end of line".
_PACIENTE_LINE = re.compile(r"\[PACIENTE\]\s*(.+?)(?=\s*\[(?:PACIENTE|OTRO)\]|\s*$)", re.DOTALL)

# Per-patient guard for scheduling journal summarization. Keyed by patient_id,
# value is the last UTC datetime when a summarization was *scheduled*.
_last_journal_ts: dict[int, datetime] = {}
_last_journal_lock = Lock()


def _extract_patient_lines(transcript_text: str) -> list[str]:
    """Return only the [PACIENTE] fragments from a tagged transcript.

    For transcripts without speaker tags (no voice sample enrolled) we
    treat the whole text as patient-spoken.
    """
    if not transcript_text:
        return []
    if "[PACIENTE]" not in transcript_text and "[OTRO]" not in transcript_text:
        return [transcript_text.strip()] if transcript_text.strip() else []
    return [m.group(1).strip() for m in _PACIENTE_LINE.finditer(transcript_text) if m.group(1).strip()]


def get_short_term(
    patient_id: int,
    db: Session,
    now: datetime | None = None,
    window_minutes: int | None = None,
    max_utterances: int | None = None,
    max_chars: int | None = None,
    exclude_transcript_id: int | None = None,
) -> str:
    """Build the STM string for a patient.

    Format: one line per utterance, newest first:
        [HH:MM] texto

    Truncated oldest-first to respect max_chars. Returns "" if there is
    nothing to show.
    """
    now = now or datetime.now(timezone.utc)
    window_minutes = window_minutes or config.STM_WINDOW_MINUTES
    max_utterances = max_utterances or config.STM_MAX_UTTERANCES
    max_chars = max_chars or config.STM_MAX_CHARS

    cutoff = now - timedelta(minutes=window_minutes)
    # started_at is stored naive UTC; strip tzinfo for the comparison.
    cutoff_naive = cutoff.replace(tzinfo=None)

    q = (
        db.query(Transcript)
        .filter(Transcript.patient_id == patient_id)
        .filter(Transcript.started_at >= cutoff_naive)
    )
    if exclude_transcript_id is not None:
        q = q.filter(Transcript.id != exclude_transcript_id)
    rows = q.order_by(Transcript.started_at.desc()).limit(max_utterances * 3).all()

    lines: list[str] = []  # newest-first
    for row in rows:
        ts = row.started_at.strftime("%H:%M")
        for frag in _extract_patient_lines(row.transcript_text):
            lines.append(f"[{ts}] {frag}")
            if len(lines) >= max_utterances:
                break
        if len(lines) >= max_utterances:
            break

    if not lines:
        return ""

    # Oldest-first is easier for an LLM to read as a narrative.
    lines.reverse()

    # Enforce char cap by dropping oldest until it fits.
    total = sum(len(l) + 1 for l in lines)
    while total > max_chars and len(lines) > 1:
        dropped = lines.pop(0)
        total -= len(dropped) + 1

    return "\n".join(lines)


def should_schedule_journal(patient_id: int, now: datetime | None = None) -> bool:
    """Check whether enough time has passed since the last journal run for this patient."""
    now = now or datetime.now(timezone.utc)
    interval = timedelta(minutes=config.JOURNAL_INTERVAL_MINUTES)
    with _last_journal_lock:
        last = _last_journal_ts.get(patient_id)
        if last is not None and now - last < interval:
            return False
        _last_journal_ts[patient_id] = now
        return True


async def summarize_and_append(patient_id: int) -> None:
    """Background task: condense the current STM into one journal entry.

    Opens its own DB session so it is decoupled from the request.
    Silently no-ops when there is not enough material.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        stm = get_short_term(patient_id, db, now=now)
        if not stm:
            logger.debug(f"[journal] patient={patient_id}: STM empty, skipping.")
            return

        # Require at least 3 utterances worth of material.
        if stm.count("\n") < 2:
            logger.debug(f"[journal] patient={patient_id}: STM too small ({stm.count(chr(10)) + 1} lines), skipping.")
            return

        # Ask the LLM for a short third-person summary.
        system = (
            "Eres un asistente que escribe un diario del día de una persona con demencia. "
            "Resume lo que ha hecho o dicho en tercera persona, en 1 o 2 frases cortas, "
            "neutro y factual, máximo 30 palabras. Responde SOLO con el resumen, sin comillas ni prefijos."
        )
        user_msg = (
            "Transcripciones recientes (hora entre corchetes, sólo frases del paciente):\n"
            f"{stm}\n\n"
            "Escribe una entrada de diario."
        )
        llm = get_llm_provider()
        raw = await llm.generate(system, user_msg)
        summary = (raw or "").strip().strip('"').strip("'")
        if not summary:
            logger.debug(f"[journal] patient={patient_id}: LLM returned empty summary.")
            return
        if len(summary) > 500:
            summary = summary[:497].rstrip() + "..."

        # covers_start / covers_end: the window we summarized over.
        covers_end_naive = now.replace(tzinfo=None)
        covers_start_naive = (now - timedelta(minutes=config.STM_WINDOW_MINUTES)).replace(tzinfo=None)

        entry = JournalEntry(
            patient_id=patient_id,
            covers_start=covers_start_naive,
            covers_end=covers_end_naive,
            summary_text=summary,
        )
        db.add(entry)
        db.flush()

        # Retention: drop entries older than the retention window, then hard-cap rows.
        retention_cutoff = now - timedelta(hours=config.JOURNAL_RETENTION_HOURS)
        db.execute(
            delete(JournalEntry)
            .where(JournalEntry.patient_id == patient_id)
            .where(JournalEntry.created_at < retention_cutoff.replace(tzinfo=None))
        )

        total = (
            db.query(JournalEntry)
            .filter(JournalEntry.patient_id == patient_id)
            .count()
        )
        if total > config.JOURNAL_MAX_ENTRIES:
            excess = total - config.JOURNAL_MAX_ENTRIES
            oldest = (
                db.query(JournalEntry)
                .filter(JournalEntry.patient_id == patient_id)
                .order_by(JournalEntry.created_at.asc())
                .limit(excess)
                .all()
            )
            for o in oldest:
                db.delete(o)

        # Transcript retention: time-based + hard row cap per patient.
        # Cheap because it piggybacks on this already-scheduled task.
        tx_cutoff = now - timedelta(days=config.TRANSCRIPT_RETENTION_DAYS)
        db.execute(
            delete(Transcript)
            .where(Transcript.patient_id == patient_id)
            .where(Transcript.created_at < tx_cutoff.replace(tzinfo=None))
        )
        tx_total = (
            db.query(Transcript)
            .filter(Transcript.patient_id == patient_id)
            .count()
        )
        if tx_total > config.TRANSCRIPT_MAX_ROWS:
            tx_excess = tx_total - config.TRANSCRIPT_MAX_ROWS
            tx_oldest = (
                db.query(Transcript)
                .filter(Transcript.patient_id == patient_id)
                .order_by(Transcript.created_at.asc())
                .limit(tx_excess)
                .all()
            )
            for t in tx_oldest:
                db.delete(t)

        db.commit()
        logger.info(f"[journal] patient={patient_id}: stored entry '{summary[:80]}...'")
    except Exception as e:
        db.rollback()
        logger.warning(f"[journal] patient={patient_id}: summarization failed: {e}")
    finally:
        db.close()
