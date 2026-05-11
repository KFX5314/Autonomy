"""
Audio processing route - receives audio chunks from patient app,
runs STT + episode detection, returns result.
"""

import asyncio
import tempfile
import os
import shutil
import time
import subprocess
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..models.transcript import Transcript
from ..models.alert import Alert
from ..schemas.alert import AudioChunkResponse
from ..auth import require_patient
from ..services.stt_service import transcribe_audio
from ..services.episode_detector import EpisodeDetector, _extract_patient_text
from ..services.speaker_id_service import diarize_segments, build_tagged_transcript
from ..services.tts_echo_service import detect_tts_echo, normalize_tts_text, tag_as_assistant
from ..services.memory_service import (
    get_short_term,
    should_schedule_journal,
    summarize_and_append,
)
from ..services.alert_audio_retention import enforce_patient_audio_cap
from ..config import config

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])

# Cap concurrent heavy audio processing (STT + diarization + LLM) to avoid
# GPU OOM and keep Ollama queue depth bounded. Created lazily at first use
# so it binds to the running event loop.
_audio_semaphore: asyncio.Semaphore | None = None


def _get_audio_semaphore() -> asyncio.Semaphore:
    global _audio_semaphore
    if _audio_semaphore is None:
        _audio_semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_AUDIO)
    return _audio_semaphore


# Accept common container types for mobile-recorded audio.
_ALLOWED_AUDIO_MIME = {
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/webm",
    "audio/ogg",
    "audio/3gpp",
}


def _validate_audio_mime(file: UploadFile) -> None:
    ct = (file.content_type or "").lower().split(";")[0].strip()
    if ct and ct not in _ALLOWED_AUDIO_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported audio type: {ct}")


def _response_segments(segments: list[dict]) -> list[dict]:
    out: list[dict] = []
    for s in segments:
        item = {"start": s["start"], "end": s["end"]}
        for key in ("speaker", "speaker_similarity", "speaker_confidence"):
            if key in s:
                item[key] = s[key]
        out.append(item)
    return out


def _has_recent_assistant_transcript(
    db: Session,
    patient_id: int,
    text: str | None,
    now: datetime,
) -> bool:
    if not text:
        return False
    target = normalize_tts_text(text)
    if not target:
        return False
    cutoff = (now - timedelta(milliseconds=config.TTS_ECHO_MATCH_WINDOW_MS)).replace(tzinfo=None)
    rows = (
        db.query(Transcript)
        .filter(Transcript.patient_id == patient_id)
        .filter(Transcript.started_at >= cutoff)
        .filter(Transcript.transcript_text.like("[ASSISTANT]%"))
        .order_by(Transcript.started_at.desc())
        .limit(10)
        .all()
    )
    return any(normalize_tts_text(row.transcript_text) == target for row in rows)


def _store_assistant_transcript(db: Session, patient_id: int, reply_text: str | None) -> None:
    if not reply_text or not reply_text.strip():
        return
    now = datetime.now(timezone.utc)
    if _has_recent_assistant_transcript(db, patient_id, reply_text, now):
        return
    db.add(Transcript(
        patient_id=patient_id,
        started_at=now,
        ended_at=now,
        lang="es",
        transcript_text=tag_as_assistant(reply_text),
        stt_model="assistant_tts",
    ))


@router.post("/chunk", response_model=AudioChunkResponse)
async def process_audio_chunk(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    recent_tts_text: str | None = Form(default=None),
    recent_tts_age_ms: int | None = Form(default=None),
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
    _validate_audio_mime(file)

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

    async with _get_audio_semaphore():
        try:
                t0 = time.time()
                print(f"\n\033[96m{'='*60}\033[0m")
                print(f"\033[96m  >> AUDIO RECIBIDO {datetime.now().strftime('%H:%M:%S.%f')[:-3]}\033[0m")

                # 0. Check audio duration -- reject files > 30s
                MAX_AUDIO_SECONDS = 30
                audio_duration = None
                try:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
                        capture_output=True, text=True, timeout=5,
                    )
                    audio_duration = float(probe.stdout.strip())
                    print(f"\033[96m  [DUR] DURACION AUDIO: {audio_duration:.1f}s\033[0m")
                    if audio_duration > MAX_AUDIO_SECONDS:
                        print(f"\033[93m  [!] Audio demasiado largo ({audio_duration:.1f}s > {MAX_AUDIO_SECONDS}s) -- descartado\033[0m")
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

                print(f"\033[96m  >> WHISPER ({config.STT_MODEL}): {t_stt_end - t_stt_start:.2f}s\033[0m")

                if not transcript_text.strip():
                    print("\033[90m  ... silencio / audio vacio (o alucinacion filtrada)\033[0m")
                    return AudioChunkResponse(
                        transcript="", episode=False, severity=0,
                        reason="Silencio o audio no reconocido",
                    )

                print(f"\033[96m  [TXT] {transcript_text}\033[0m")

                # 1b. Recognize leaked app TTS before speaker verification.
                # The transcript is still stored because [ASSISTANT] is useful
                # short-term context, but it must never fire an alert.
                is_assistant_echo = False
                t_diar_start = time.time()
                echo_match = detect_tts_echo(transcript_text, recent_tts_text, recent_tts_age_ms)
                if echo_match:
                    is_assistant_echo = True
                    transcript_text = tag_as_assistant(transcript_text)
                    for seg in segments:
                        seg["speaker"] = "ASSISTANT"
                        seg["speaker_confidence"] = "tts_echo"
                    print(
                        f"\033[94m  [TTS] Eco del asistente detectado "
                        f"(ratio {echo_match.ratio:.2f}, edad {echo_match.recent_tts_age_ms} ms)\033[0m"
                    )
                    print(f"\033[96m  [TAG] TRANSCRIPCION ETIQUETADA:\033[0m")
                    print(f"     {transcript_text}")
                elif patient.voice_embedding and segments:
                    segments = diarize_segments(
                        tmp_path, segments, patient.voice_embedding
                    )
                    transcript_text = build_tagged_transcript(segments)
                    print(f"\033[96m  [TAG] TRANSCRIPCION ETIQUETADA:\033[0m")
                    for line in transcript_text.split("\n"):
                        print(f"     {line}")
                else:
                    if not patient.voice_embedding:
                        print("\033[93m  [!] Sin muestra de voz - no se identifica hablante\033[0m")
                t_diar_end = time.time()
                print(f"\033[96m  >> DIARIZACION:    {t_diar_end - t_diar_start:.2f}s\033[0m")

                # 2. Store transcript. Assistant echo chunks are stored unless
                # the same assistant reply was already persisted when generated.
                duplicate_assistant_echo = is_assistant_echo and _has_recent_assistant_transcript(
                    db,
                    patient.id,
                    recent_tts_text or transcript_text,
                    now,
                )
                transcript = None
                if not duplicate_assistant_echo:
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

                if is_assistant_echo:
                    db.commit()
                    stored_msg = "transcript guardado" if not duplicate_assistant_echo else "duplicado omitido"
                    print(f"\033[92m  [OK] ECO ASSISTANT: {stored_msg}, sin alerta\033[0m")
                    print(f"\033[96m  >> TOTAL:          {time.time() - t0:.2f}s\033[0m")
                    print(f"\033[96m{'='*60}\033[0m\n")
                    return AudioChunkResponse(
                        transcript=transcript_text,
                        episode=False,
                        severity=0,
                        reason="Eco TTS del asistente",
                        reply_text=None,
                        alert_id=None,
                        mode="idle",
                        segments=_response_segments(segments),
                    )

                # 3. Episode detection (with short-term memory injected for context)
                ctx = db.query(PatientContext).filter(PatientContext.patient_id == patient.id).first()
                context_data = ctx.context_json if ctx else {}

                stm = get_short_term(patient.id, db, exclude_transcript_id=transcript.id)
                if stm:
                    print(f"\033[96m  [STM] {stm.count(chr(10)) + 1} utterance(s), {len(stm)} chars\033[0m")

                # 3a. Wake-word shortcut: if the patient says a configured
                # wake word, skip the episode detector and answer the query.
                wake_words = [w.lower() for w in context_data.get("assistant_wake_words", []) if isinstance(w, str) and w.strip()]
                patient_only_text = _extract_patient_text(transcript_text).lower()
                triggered_wake = next((w for w in wake_words if w and w in patient_only_text), None)

                if triggered_wake:
                    from ..services.assistant_service import answer_patient_query

                    # Build the full question for the LLM by combining:
                    # 1. The current transcript (full, including [OTRO] context)
                    # 2. The patient's own text from this chunk (after removing
                    #    the wake word itself so it doesn't confuse the LLM)
                    # The STM is also passed and injected into the prompt by
                    # answer_patient_query, giving the LLM the recent
                    # conversation history to answer questions like
                    # "what time did I have to buy bread?"
                    query_text = patient_only_text.replace(triggered_wake, "").strip()
                    if not query_text:
                        # The wake word was the only thing said — use the full
                        # transcript (which may include [OTRO] lines giving
                        # context) so the LLM still has something to work with.
                        query_text = transcript_text.strip()

                    t_llm_start = time.time()
                    assistant_out = await answer_patient_query(
                        patient=patient,
                        patient_text=query_text,
                        full_transcript=transcript_text,
                        stm=stm,
                        db=db,
                    )
                    t_llm_end = time.time()
                    print(f"\033[94m  [WAKE] '{triggered_wake}' -> assistant reply in {t_llm_end - t_llm_start:.2f}s\033[0m")
                    if assistant_out.get("reply_text"):
                        print(f"\033[94m     Respuesta: {assistant_out['reply_text'][:120]}\033[0m")
                        _store_assistant_transcript(db, patient.id, assistant_out.get("reply_text"))
                    db.commit()

                    if should_schedule_journal(patient.id):
                        background_tasks.add_task(summarize_and_append, patient.id)

                    return AudioChunkResponse(
                        transcript=transcript_text,
                        episode=False,
                        severity=0,
                        reason="",
                        reply_text=assistant_out.get("reply_text"),
                        alert_id=None,
                        mode="assistant",
                        segments=_response_segments(segments),
                    )

                detector = EpisodeDetector(context_data)
                t_llm_start = time.time()
                result = await detector.analyze(transcript_text, short_term_memory=stm)
                t_llm_end = time.time()
                print(f"\033[96m  >> LLM ({config.LLM_MODEL}): {t_llm_end - t_llm_start:.2f}s\033[0m")

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

                    # Archive the audio so the caregiver can replay the episode.
                    # On failure we swallow: the alert is still useful without audio.
                    try:
                        patient_dir = os.path.join(config.ALERTS_AUDIO_DIR, str(patient.id))
                        os.makedirs(patient_dir, exist_ok=True)
                        ext = os.path.splitext(tmp_path)[1] or ".wav"
                        archive_path = os.path.join(patient_dir, f"{alert_id}{ext}")
                        shutil.move(tmp_path, archive_path)
                        alert.audio_path = archive_path
                        enforce_patient_audio_cap(db, patient.id)
                        tmp_path = None  # signal finally block not to unlink
                    except Exception as e:
                        logger.warning(f"Could not archive alert audio: {e}")

                    if result.llm_response:
                        _store_assistant_transcript(db, patient.id, result.llm_response)

                db.commit()

                # --- Debug: show result ---
                if result.is_episode:
                    print(f"\033[91m  [ALERTA] SI (severidad {result.severity})\033[0m")
                    print(f"\033[91m     Razon: {result.reason}\033[0m")
                    if result.llm_response:
                        print(f"\033[93m     Respuesta: {result.llm_response[:120]}\033[0m")
                else:
                    print(f"\033[92m  [OK] ALERTA: NO\033[0m")
                print(f"\033[96m  >> TOTAL:          {time.time() - t0:.2f}s\033[0m")
                print(f"\033[96m{'='*60}\033[0m\n")

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
                    mode="episode" if result.is_episode else "idle",
                    segments=_response_segments(segments),
                )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
