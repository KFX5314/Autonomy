"""
Alert routes - used by caregivers to monitor and acknowledge alerts.
"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..auth import require_caregiver
from ..database import get_db
from ..models.alert import Alert
from ..models.patient import Patient
from ..models.transcript import Transcript
from ..models.user import User
from ..schemas.alert import AlertAck, AlertOut
from ..services.alert_audio_retention import delete_alert_audio

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


@router.post("/{alert_id}/ack", response_model=AlertOut)
def acknowledge_alert(
    alert_id: int,
    body: AlertAck,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Acknowledge an alert and delete its archived audio immediately."""
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not _caregiver_owns_alert(db, alert, user):
        raise HTTPException(status_code=403, detail="Not your patient's alert")
    if body.status.upper() != "ACK":
        raise HTTPException(status_code=400, detail="Status must be ACK")

    alert.status = "ACK"
    alert.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if alert.audio_path:
        delete_alert_audio(alert, reason="ACK cleanup")

    db.commit()
    db.refresh(alert)

    transcript_text = None
    if alert.transcript_id:
        tx = db.query(Transcript).filter(Transcript.id == alert.transcript_id).first()
        if tx:
            transcript_text = tx.transcript_text
    return _serialize_alert(alert, transcript_text)
