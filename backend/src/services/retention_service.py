"""Opportunistic retention cleanup used by caregiver reads."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import config
from ..models.journal import JournalEntry
from ..models.transcript import Transcript
from .alert_audio_retention import cleanup_alert_audio_retention

logger = logging.getLogger(__name__)


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _trim_journal(db: Session, patient_id: int, now: datetime) -> int:
    cutoff = _naive_utc(now - timedelta(hours=config.JOURNAL_RETENTION_HOURS))
    result = db.execute(
        delete(JournalEntry)
        .where(JournalEntry.patient_id == patient_id)
        .where(JournalEntry.created_at < cutoff)
    )
    deleted = result.rowcount or 0

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
        for entry in oldest:
            db.delete(entry)
        deleted += len(oldest)
    return deleted


def _trim_transcripts(db: Session, patient_id: int, now: datetime) -> int:
    cutoff = _naive_utc(now - timedelta(days=config.TRANSCRIPT_RETENTION_DAYS))
    result = db.execute(
        delete(Transcript)
        .where(Transcript.patient_id == patient_id)
        .where(Transcript.created_at < cutoff)
    )
    deleted = result.rowcount or 0

    total = db.query(Transcript).filter(Transcript.patient_id == patient_id).count()
    if total > config.TRANSCRIPT_MAX_ROWS:
        excess = total - config.TRANSCRIPT_MAX_ROWS
        oldest = (
            db.query(Transcript)
            .filter(Transcript.patient_id == patient_id)
            .order_by(Transcript.created_at.asc())
            .limit(excess)
            .all()
        )
        for transcript in oldest:
            db.delete(transcript)
        deleted += len(oldest)
    return deleted


def cleanup_patient_retention(db: Session, patient_id: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "journal_deleted": _trim_journal(db, patient_id, now),
        "transcripts_deleted": _trim_transcripts(db, patient_id, now),
        "alert_audio_deleted": cleanup_alert_audio_retention(db, [patient_id], now=now),
    }


def cleanup_patients_retention(db: Session, patient_ids: list[int], now: datetime | None = None) -> dict:
    totals = {"journal_deleted": 0, "transcripts_deleted": 0, "alert_audio_deleted": 0}
    for patient_id in patient_ids:
        result = cleanup_patient_retention(db, patient_id, now=now)
        for key, value in result.items():
            totals[key] += value
    return totals


def cleanup_patient_retention_safely(db: Session, patient_id: int) -> None:
    cleanup_patients_retention_safely(db, [patient_id])


def cleanup_patients_retention_safely(db: Session, patient_ids: list[int]) -> None:
    try:
        result = cleanup_patients_retention(db, patient_ids)
        db.commit()
        if any(result.values()):
            logger.info("Retention cleanup for patients %s: %s", patient_ids, result)
    except Exception as exc:
        db.rollback()
        logger.warning("Retention cleanup failed for patients %s: %s", patient_ids, exc)
