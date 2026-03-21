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

    if body.status.upper() not in ("ACK", "CLOSED"):
        raise HTTPException(status_code=400, detail="Status must be ACK or CLOSED")

    alert.status = body.status.upper()
    db.commit()
    db.refresh(alert)
    return alert
