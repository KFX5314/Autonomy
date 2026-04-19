"""
Audio processing route - receives audio chunks from patient app,
runs STT + episode detection, returns result.
"""

import tempfile
import os
import time
import subprocess
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException
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
from ..services.speaker_id_service import diarize_segments, build_tagged_transcript
from ..services.memory_service import (
    get_short_term,
    should_schedule_journal,
    summarize_and_append,
)
from ..config import config

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])


@router.post("/chunk", response_model=AudioChunkResponse)
async def process_audio_chunk(
    background_tasks: BackgroundTasks,
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
        t0 = time.time()
        print(f"\n\033[96m{'═'*60}\033[0m")
        print(f"\033[96m  ⏱  AUDIO RECIBIDO {datetime.now().strftime('%H:%M:%S.%f')[:-3]}\033[0m")

        # 0. Check audio duration — reject files > 30s
        MAX_AUDIO_SECONDS = 30
        audio_duration = None
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
                capture_output=True, text=True, timeout=5,
            )
            audio_duration = float(probe.stdout.strip())
            print(f"\033[96m  📏 DURACIÓN AUDIO: {audio_duration:.1f}s\033[0m")
            if audio_duration > MAX_AUDIO_SECONDS:
                print(f"\033[93m  ⚠  Audio demasiado largo ({audio_duration:.1f}s > {MAX_AUDIO_SECONDS}s) — descartado\033[0m")
                return AudioChunkResponse(
                    transcript="", episode=False, severity=0,
                    reason=f"Audio demasiado largo ({audio_duration:.0f}s)",
                )
        except Exception as e:
            logger.warning(f"Could not probe audio duration: {e}")

        # 1. Transcribe (with segment timestamps)
        now = datetime.now(timezone.utc)
        t_stt_start = time.time()
        stt_result = transcribe_audio(tmp_path, audio_duration=audio_duration)
        t_stt_end = time.time()
        transcript_text = stt_result["text"]
        segments = stt_result.get("segments", [])

        print(f"\033[96m  ⏱  WHISPER ({config.STT_MODEL}): {t_stt_end - t_stt_start:.2f}s\033[0m")

        if not transcript_text.strip():
            print("\033[90m  ... silencio / audio vacío (o alucinación filtrada)\033[0m")
            return AudioChunkResponse(
                transcript="", episode=False, severity=0,
                reason="Silencio o audio no reconocido",
            )

        print(f"\033[96m  📝 TEXTO DETECTADO:\033[0m {transcript_text}")

        # 1b. Per-segment speaker diarization (if voice sample enrolled)
        t_diar_start = time.time()
        if patient.voice_embedding and segments:
            segments = diarize_segments(
                tmp_path, segments, patient.voice_embedding
            )
            transcript_text = build_tagged_transcript(segments)
            print(f"\033[96m  📋 TRANSCRIPCIÓN ETIQUETADA:\033[0m")
            for line in transcript_text.split("\n"):
                print(f"     {line}")
        else:
            if not patient.voice_embedding:
                print("\033[93m  ⚠  Sin muestra de voz - no se identifica hablante\033[0m")
        t_diar_end = time.time()
        print(f"\033[96m  ⏱  DIARIZACIÓN:    {t_diar_end - t_diar_start:.2f}s\033[0m")

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

        # 3. Episode detection (with short-term memory injected for context)
        ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient.id).first()
        context_data = ctx.context_json if ctx else {}

        stm = get_short_term(patient.id, db, exclude_transcript_id=transcript.id)
        if stm:
            print(f"\033[96m  🧠 STM: {stm.count(chr(10)) + 1} utterance(s), {len(stm)} chars\033[0m")

        detector = EpisodeDetector(context_data)
        t_llm_start = time.time()
        result = await detector.analyze(transcript_text, short_term_memory=stm)
        t_llm_end = time.time()
        print(f"\033[96m  ⏱  LLM ({config.LLM_MODEL}): {t_llm_end - t_llm_start:.2f}s\033[0m")

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

        # --- Debug: show result ---
        if result.is_episode:
            print(f"\033[91m  🚨 ALERTA: SÍ  (severidad {result.severity})\033[0m")
            print(f"\033[91m     Razón: {result.reason}\033[0m")
            if result.llm_response:
                print(f"\033[93m     Respuesta: {result.llm_response[:120]}\033[0m")
        else:
            print(f"\033[92m  ✅ ALERTA: NO\033[0m")
        print(f"\033[96m  ⏱  TOTAL:          {time.time() - t0:.2f}s\033[0m")
        print(f"\033[96m{'═'*60}\033[0m\n")

        # 4. Fire-and-forget: condense the STM buffer into a journal entry.
        # Gated per-patient so it runs at most every JOURNAL_INTERVAL_MINUTES.
        if should_schedule_journal(patient.id):
            background_tasks.add_task(summarize_and_append, patient.id)

        return AudioChunkResponse(
            transcript=transcript_text,
            episode=result.is_episode,
            severity=result.severity or 0,
            reason=result.reason or "",
            reply_text=result.llm_response,
            alert_id=alert_id,
            segments=[{"start": s["start"], "end": s["end"]} for s in segments],
        )
    finally:
        os.unlink(tmp_path)
