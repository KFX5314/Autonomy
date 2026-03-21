"""
Patient management routes - used by caregivers.
"""

import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..schemas.patient import PatientOut, PatientContextUpdate, PatientContextOut
from ..auth import require_caregiver
from ..services.speaker_id_service import create_embedding

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/", response_model=list[PatientOut])
def list_patients(db: Session = Depends(get_db), user: User = Depends(require_caregiver)):
    """List all patients linked to this caregiver."""
    patient_users = db.query(User).filter(
        User.caregiver_id == user.id, User.role == "patient"
    ).all()

    results = []
    for pu in patient_users:
        p = db.query(Patient).filter(Patient.user_id == pu.id).first()
        if p:
            results.append(PatientOut(
                id=p.id,
                user_id=pu.id,
                full_name=pu.full_name,
                birth_date=p.birth_date,
                notes=p.notes,
                created_at=p.created_at,
            ))
    return results


@router.get("/{patient_id}/context", response_model=PatientContextOut)
def get_context(patient_id: int, db: Session = Depends(get_db), user: User = Depends(require_caregiver)):
    """Get patient context JSON."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Verify the patient belongs to this caregiver
    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    if not patient_user or patient_user.caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your patient")

    ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient_id).first()
    if not ctx:
        raise HTTPException(status_code=404, detail="Context not found")
    return ctx


@router.put("/{patient_id}/context", response_model=PatientContextOut)
def update_context(
    patient_id: int,
    body: PatientContextUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Update patient context JSON."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    if not patient_user or patient_user.caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your patient")

    ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient_id).first()
    if not ctx:
        ctx = PatientContext(patient_id=patient_id, context_json=body.context_json)
        db.add(ctx)
    else:
        ctx.context_json = body.context_json

    db.commit()
    db.refresh(ctx)
    return ctx


@router.post("/{patient_id}/voice-sample")
def upload_voice_sample(
    patient_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Upload a voice sample (.wav) to enroll the patient's voice."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    if not patient_user or patient_user.caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your patient")

    # Save to temp file, generate embedding, clean up
    suffix = os.path.splitext(file.filename or "sample.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        embedding = create_embedding(tmp_path)
        patient.voice_embedding = embedding
        db.commit()
        return {"status": "ok", "message": "Voice sample enrolled", "embedding_size": len(embedding)}
    finally:
        os.unlink(tmp_path)
