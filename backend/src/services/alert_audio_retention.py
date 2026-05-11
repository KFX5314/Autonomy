"""Retention helpers for archived alert audio."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..config import config
from ..database import SessionLocal
from ..models.alert import Alert

logger = logging.getLogger(__name__)


def delete_alert_audio(alert: Alert, reason: str = "cleanup") -> bool:
    """Delete an alert's archived audio and clear the DB path on success."""
    if not alert.audio_path:
        return False

    path = alert.audio_path
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError as e:
            logger.warning(f"{reason}: could not delete alert audio {path}: {e}")
            return False

    alert.audio_path = None
    return True


def enforce_patient_audio_cap(db: Session, patient_id: int) -> int:
    """Keep at most ALERT_AUDIO_MAX_FILES_PER_PATIENT archived audios for one patient."""
    max_files = max(0, config.ALERT_AUDIO_MAX_FILES_PER_PATIENT)
    alerts = (
        db.query(Alert)
        .filter(Alert.patient_id == patient_id)
        .filter(Alert.audio_path.isnot(None))
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .all()
    )
    old_alerts = alerts[max_files:]
    cleaned = 0
    for alert in old_alerts:
        if delete_alert_audio(alert, reason="audio cap"):
            cleaned += 1
    return cleaned


def sweep_expired_alert_audio() -> None:
    """Startup sweep: remove expired alert audio and enforce per-patient caps."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=config.ALERT_AUDIO_MAX_DAYS
        )
        expired = (
            db.query(Alert)
            .filter(Alert.audio_path.isnot(None))
            .filter(Alert.created_at < cutoff)
            .all()
        )
        for alert in expired:
            delete_alert_audio(alert, reason="age sweep")

        patient_ids = [
            row[0]
            for row in db.query(Alert.patient_id)
            .filter(Alert.audio_path.isnot(None))
            .distinct()
            .all()
        ]
        cap_cleaned = sum(enforce_patient_audio_cap(db, patient_id) for patient_id in patient_ids)

        db.commit()
        if expired or cap_cleaned:
            logger.info(
                "Alert-audio sweep cleaned %s expired files and %s files over cap",
                len(expired),
                cap_cleaned,
            )
    except Exception as e:
        logger.warning(f"Alert-audio sweep failed: {e}")
        db.rollback()
    finally:
        db.close()
