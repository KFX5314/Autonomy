"""
Audio processing route — receives audio chunks from patient app,
runs STT + episode detection, returns result.
"""

import tempfile
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..models.transcript import Transcript
from ..models.alert import Alert
from ..schemas.alert import AudioChunkResponse
from ..auth import require_patient
from ..services.stt_service import transcribe_audio
from ..services.episode_detector import EpisodeDetector
from ..config import config

router = APIRouter(prefix="/audio", tags=["audio"])


@router.post("/chunk", response_model=AudioChunkResponse)
async def process_audio_chunk(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_patient),
):
    """
    Receive an audio chunk from the patient app.
    1. Save temp file
    2. Transcribe with Whisper
    3. Run episode detection
    4. Store transcript + alert if needed
    5. Return result to app
    """
    # Get patient profile
    patient = db.query(Patient).filter(Patient.user_id == user.id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient profile not found")

    # Save uploaded audio to temp file
    suffix = os.path.splitext(file.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # 1. Transcribe
        now = datetime.now(timezone.utc)
        stt_result = transcribe_audio(tmp_path)
        transcript_text = stt_result["text"]

        if not transcript_text.strip():
            return AudioChunkResponse(
                transcript="", episode=False, severity=0,
                reason="Silencio o audio no reconocido",
            )

        # 2. Store transcript
        transcript = Transcript(
            patient_id=patient.id,
            started_at=now,
            ended_at=datetime.now(timezone.utc),
            lang=stt_result.get("language", "es"),
            transcript_text=transcript_text,
            stt_model=config.STT_MODEL,
        )
        db.add(transcript)
        db.flush()

        # 3. Episode detection
        ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient.id).first()
        context_data = ctx.context_json if ctx else {}

        detector = EpisodeDetector(context_data)
        result = await detector.analyze(transcript_text)

        alert_id = None
        if result.is_episode:
            alert = Alert(
                patient_id=patient.id,
                transcript_id=transcript.id,
                severity=result.severity,
                reason=result.reason,
                llm_response=result.llm_response,
                status="NEW",
            )
            db.add(alert)
            db.flush()
            alert_id = alert.id

        db.commit()

        return AudioChunkResponse(
            transcript=transcript_text,
            episode=result.is_episode,
            severity=result.severity or 0,
            reason=result.reason or "",
            reply_text=result.llm_response,
            alert_id=alert_id,
        )
    finally:
        os.unlink(tmp_path)
