"""
Alert routes - used by caregivers to monitor and acknowledge alerts.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import require_caregiver
from ..config import config
from ..database import SessionLocal, get_db
from ..models.alert import Alert
from ..models.patient import Patient
from ..models.transcript import Transcript
from ..models.user import User
from ..schemas.alert import AlertAck, AlertOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])


def _serialize_alert(alert: Alert, transcript_text: str | None) -> dict:
    audio_url = f"/alerts/{alert.id}/audio" if alert.audio_path else None
    return {
        "id": alert.id,
        "patient_id": alert.patient_id,
        "severity": alert.severity,
        "reason": alert.reason,
        "llm_response": alert.llm_response,
        "status": alert.status,
        "transcript_text": transcript_text,
        "audio_url": audio_url,
        "created_at": alert.created_at,
        "acknowledged_at": alert.acknowledged_at,
    }


def _caregiver_owns_alert(db: Session, alert: Alert, user: User) -> bool:
    patient = db.query(Patient).filter(Patient.id == alert.patient_id).first()
    if not patient:
        return False
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    return bool(patient_user and patient_user.caregiver_id == user.id)


@router.get("/", response_model=list[AlertOut])
def list_alerts(
    patient_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """List alerts for patients of this caregiver, with transcript + audio_url."""
    patient_users = db.query(User).filter(
        User.caregiver_id == user.id, User.role == "patient"
    ).all()
    patient_user_ids = [pu.id for pu in patient_users]

    patients = db.query(Patient).filter(Patient.user_id.in_(patient_user_ids)).all()
    patient_ids = [p.id for p in patients]

    query = db.query(Alert).filter(Alert.patient_id.in_(patient_ids))
    if patient_id is not None:
        if patient_id not in patient_ids:
            raise HTTPException(status_code=403, detail="Not your patient")
        query = query.filter(Alert.patient_id == patient_id)
    if status:
        query = query.filter(Alert.status == status.upper())

    alerts = query.order_by(Alert.created_at.desc()).all()

    # Resolve transcripts in a single query to avoid N+1.
    transcript_ids = [a.transcript_id for a in alerts if a.transcript_id]
    tx_map: dict[int, str] = {}
    if transcript_ids:
        for t in db.query(Transcript).filter(Transcript.id.in_(transcript_ids)).all():
            tx_map[t.id] = t.transcript_text

    return [_serialize_alert(a, tx_map.get(a.transcript_id)) for a in alerts]


@router.get("/{alert_id}/audio")
def get_alert_audio(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Stream the archived audio chunk for an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _caregiver_owns_alert(db, alert, user):
        raise HTTPException(status_code=403, detail="Not your patient's alert")
    if not alert.audio_path or not os.path.exists(alert.audio_path):
        raise HTTPException(status_code=404, detail="Audio no longer available")

    ext = os.path.splitext(alert.audio_path)[1].lower()
    media_type = {
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
    }.get(ext, "application/octet-stream")
    return FileResponse(alert.audio_path, media_type=media_type)


def _cleanup_alert_audio_after_ack(alert_id: int) -> None:
    """Background: drop archived audio after ALERT_AUDIO_ACK_GRACE_HOURS if still ACK'd."""
    import time as _time
    _time.sleep(config.ALERT_AUDIO_ACK_GRACE_HOURS * 3600)

    db = SessionLocal()
    try:
        alert = db.query(Alert).filter(Alert.id == alert_id).first()
        if not alert or alert.status != "ACK" or not alert.audio_path:
            return
        if os.path.exists(alert.audio_path):
            try:
                os.remove(alert.audio_path)
            except OSError as e:
                logger.warning(f"Could not delete alert audio {alert.audio_path}: {e}")
        alert.audio_path = None
        db.commit()
    finally:
        db.close()


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    body: AlertAck,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Acknowledge an alert and schedule its archived audio for deletion."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _caregiver_owns_alert(db, alert, user):
        raise HTTPException(status_code=403, detail="Not your patient's alert")
    if body.status.upper() != "ACK":
        raise HTTPException(status_code=400, detail="Status must be ACK")

    alert.status = "ACK"
    alert.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(alert)

    if alert.audio_path:
        background_tasks.add_task(_cleanup_alert_audio_after_ack, alert.id)

    transcript_text = None
    if alert.transcript_id:
        tx = db.query(Transcript).filter(Transcript.id == alert.transcript_id).first()
        if tx:
            transcript_text = tx.transcript_text
    return _serialize_alert(alert, transcript_text)


def sweep_expired_alert_audio() -> None:
    """Startup sweep: drop alert audio older than ALERT_AUDIO_MAX_DAYS regardless of ACK."""
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
            if alert.audio_path and os.path.exists(alert.audio_path):
                try:
                    os.remove(alert.audio_path)
                except OSError as e:
                    logger.warning(f"Sweep: could not delete {alert.audio_path}: {e}")
            alert.audio_path = None
        db.commit()
        if expired:
            logger.info(f"Alert-audio sweep cleaned {len(expired)} old files")
    except Exception as e:
        logger.warning(f"Alert-audio sweep failed: {e}")
        db.rollback()
    finally:
        db.close()
"""
Alert routes - used by caregivers to monitor and acknowledge alerts.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient
from ..models.alert import Alert
from ..schemas.alert import AlertOut, AlertAck
from ..auth import require_caregiver

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/", response_model=list[AlertOut])
def list_alerts(
    patient_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """List alerts for patients of this caregiver."""
    # Get all patient user IDs for this caregiver
    patient_users = db.query(User).filter(
        User.caregiver_id == user.id, User.role == "patient"
    ).all()
    patient_user_ids = [pu.id for pu in patient_users]

    patients = db.query(Patient).filter(Patient.user_id.in_(patient_user_ids)).all()
    patient_ids = [p.id for p in patients]

    query = db.query(Alert).filter(Alert.patient_id.in_(patient_ids))

    if patient_id is not None:
        if patient_id not in patient_ids:
            raise HTTPException(status_code=403, detail="Not your patient")
        query = query.filter(Alert.patient_id == patient_id)

    if status:
        query = query.filter(Alert.status == status.upper())

    return query.order_by(Alert.created_at.desc()).all()


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    body: AlertAck,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Acknowledge or close an alert."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Verify ownership
    patient = db.query(Patient).filter(Patient.id == alert.patient_id).first()
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    if patient_user.caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your patient's alert")

    if body.status.upper() != "ACK":
        raise HTTPException(status_code=400, detail="Status must be ACK")

    alert.status = body.status.upper()
    db.commit()
    db.refresh(alert)
    return alert
