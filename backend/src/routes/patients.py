"""
Patient management routes - used by caregivers.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..config import config
from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..models.journal import JournalEntry
from ..models.alert import Alert
from ..schemas.patient import PatientOut, PatientContextUpdate, PatientContextOut, ShortTermMemoryOut
from ..schemas.journal import JournalEntryOut
from ..auth import require_caregiver, require_patient
from ..services.memory_service import get_short_term
from ..services.expo_push_service import notify_caregiver_alert
from ..services.retention_service import cleanup_patient_retention_safely
from ..services.speaker_id_service import (
    MAX_VOICE_SAMPLES,
    append_voice_sample,
    create_embedding,
    delete_voice_sample,
    list_voice_samples,
)

router = APIRouter(prefix="/patients", tags=["patients"])


def _get_owned_patient(patient_id: int, db: Session, user: User) -> Patient:
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_user = db.query(User).filter(User.id == patient.user_id).first()
    if not patient_user or patient_user.caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not your patient")
    return patient


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
                username=pu.username,
                birth_date=p.birth_date,
                notes=p.notes,
                created_at=p.created_at,
            ))
    return results


@router.post("/me/logout-warning")
def create_logout_warning(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_patient),
):
    """Patient-only: notify the caregiver that the patient logged out."""
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    alert = Alert(
        patient_id=patient.id,
        severity=2,
        reason="El paciente ha cerrado sesión en la app",
        llm_response="El paciente ha cerrado sesión en la aplicación. Conviene comprobar que no ha sido accidental.",
        status="NEW",
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    if user.caregiver_id:
        background_tasks.add_task(
            notify_caregiver_alert,
            caregiver_id=user.caregiver_id,
            alert_id=alert.id,
            patient_name=user.full_name,
            severity=alert.severity,
            reason=alert.reason,
        )
    return {"status": "ok", "alert_id": alert.id}


@router.get("/me/settings")
def get_my_patient_settings(
    db: Session = Depends(get_db),
    user: User = Depends(require_patient),
):
    """Patient-only: read safe patient settings used by the mobile UI."""
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient.id).first()
    context_json = ctx.context_json if ctx else {}
    return {
        "patient_id": patient.id,
        "tts_enabled": bool(context_json.get("tts_enabled", True)),
        "ui_color": context_json.get("ui_color") or "#4A90D9",
    }


@router.get("/{patient_id}/context", response_model=PatientContextOut)
def get_context(patient_id: int, db: Session = Depends(get_db), user: User = Depends(require_caregiver)):
    """Get patient context JSON."""
    _get_owned_patient(patient_id, db, user)

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
    _get_owned_patient(patient_id, db, user)

    ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient_id).first()
    if not ctx:
        ctx = PatientContext(patient_id=patient_id, context_json=body.context_json)
        db.add(ctx)
    else:
        ctx.context_json = body.context_json

    db.commit()
    db.refresh(ctx)
    return ctx


@router.get("/{patient_id}/voice-samples")
def get_voice_samples(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """List enrolled voice samples without exposing raw embeddings."""
    patient = _get_owned_patient(patient_id, db, user)
    samples = list_voice_samples(patient.voice_embedding)
    return {"samples": samples, "count": len(samples), "max_samples": MAX_VOICE_SAMPLES}


@router.delete("/{patient_id}/voice-samples/{sample_id}")
def remove_voice_sample(
    patient_id: int,
    sample_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Delete one enrolled voice sample."""
    patient = _get_owned_patient(patient_id, db, user)
    before = list_voice_samples(patient.voice_embedding)
    if not any(sample["id"] == sample_id for sample in before):
        raise HTTPException(status_code=404, detail="Voice sample not found")

    patient.voice_embedding = delete_voice_sample(patient.voice_embedding, sample_id)
    db.commit()
    samples = list_voice_samples(patient.voice_embedding)
    return {"status": "ok", "samples": samples, "count": len(samples), "max_samples": MAX_VOICE_SAMPLES}


@router.post("/{patient_id}/voice-sample")
def upload_voice_sample(
    patient_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Upload a voice sample (.wav) to enroll the patient's voice."""
    # Mime-type allowlist (avoid parsing arbitrary binary blobs with ffprobe/torchaudio).
    _ALLOWED = {
        "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac",
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
        "audio/wave", "audio/webm", "audio/ogg", "audio/3gpp",
    }
    ct = (file.content_type or "").lower().split(";")[0].strip()
    if ct and ct not in _ALLOWED:
        raise HTTPException(status_code=415, detail=f"Unsupported audio type: {ct}")

    patient = _get_owned_patient(patient_id, db, user)

    suffix = os.path.splitext(file.filename or "sample.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        embedding = create_embedding(tmp_path)
        patient.voice_embedding = append_voice_sample(patient.voice_embedding, embedding)
        db.commit()
        samples = list_voice_samples(patient.voice_embedding)
        return {
            "status": "ok",
            "message": "Voice sample enrolled",
            "embedding_size": len(embedding),
            "count": len(samples),
            "max_samples": MAX_VOICE_SAMPLES,
            "samples": samples,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.get("/{patient_id}/short-term-memory", response_model=ShortTermMemoryOut)
def get_short_term_memory(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Caregiver-only: read the patient's current short-term memory window."""
    _get_owned_patient(patient_id, db, user)
    cleanup_patient_retention_safely(db, patient_id)

    generated_at = datetime.now(timezone.utc)
    return ShortTermMemoryOut(
        patient_id=patient_id,
        window_minutes=config.STM_WINDOW_MINUTES,
        max_utterances=config.STM_MAX_UTTERANCES,
        generated_at=generated_at,
        memory=get_short_term(patient_id, db, now=generated_at),
    )


@router.get("/{patient_id}/journal", response_model=list[JournalEntryOut])
def get_journal(
    patient_id: int,
    since_hours: int = 24,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Caregiver-only: read the patient's recent journal entries (LTM)."""
    _get_owned_patient(patient_id, db, user)
    cleanup_patient_retention_safely(db, patient_id)

    since_hours = max(1, min(since_hours, 168))  # 1 h .. 1 week
    limit = max(1, min(limit, 500))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).replace(tzinfo=None)

    rows = (
        db.query(JournalEntry)
        .filter(JournalEntry.patient_id == patient_id)
        .filter(JournalEntry.created_at >= cutoff)
        .order_by(JournalEntry.created_at.desc())
        .limit(limit)
        .all()
    )
    return rows
