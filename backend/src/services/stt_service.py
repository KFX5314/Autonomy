"""
Speech-to-Text service using faster-whisper with CUDA acceleration.

faster-whisper bundles silero-vad via ``vad_filter=True``: non-speech regions
are trimmed *before* decoding, which removes the vast majority of Whisper
hallucinations on silence (no more "Gracias por ver el vídeo" etc.).
A small phrase/timestamp/repetition filter catches residual hallucinations.
"""

import os
import logging
import sysconfig
import threading
import time
import tempfile
from collections import Counter
from difflib import SequenceMatcher
import re
import unicodedata


def _add_nvidia_dll_dirs() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    site_packages = sysconfig.get_paths().get("purelib")
    if not site_packages:
        return

    for subdir in (
        "nvidia/cublas/bin",
        "nvidia/cudnn/bin",
        "nvidia/cuda_nvrtc/bin",
        "nvidia/cuda_runtime/bin",
    ):
        dll_dir = os.path.join(site_packages, *subdir.split("/"))
        if os.path.isdir(dll_dir):
            os.add_dll_directory(dll_dir)
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")


_add_nvidia_dll_dirs()

from faster_whisper import WhisperModel

from ..config import config

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None
# Serializes access to the Whisper singleton. faster-whisper/CTranslate2 is
# not safe against concurrent inference on the same model instance (CUDA
# context + internal buffers are shared), so we gate every transcribe() call
# behind this lock. Concurrency at the request level is still bounded by the
# audio semaphore in routes/audio.py; this lock additionally serializes the
# GPU/CPU work to avoid corrupted tensors if two worker threads collide.
_model_lock = threading.Lock()


def _compute_type() -> str:
    # float16 is the recommended default on recent NVIDIA GPUs.
    # Fall back to int8 on CPU.
    if config.STT_DEVICE == "cuda":
        return "float16"
    return "int8"


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            config.STT_MODEL,
            device=config.STT_DEVICE,
            compute_type=_compute_type(),
        )
    return _model


def warmup():
    """Pre-download and load the Whisper model + silero-vad at startup."""
    logger.info(
        f"Loading faster-whisper model '{config.STT_MODEL}' on {config.STT_DEVICE} "
        f"(compute_type={_compute_type()})..."
    )
    t0 = time.time()
    model = _get_model()

    # Trigger the silero-vad download by doing a tiny transcription on silence.
    try:
        import numpy as np
        import soundfile as sf
        silence = np.zeros(16000, dtype=np.float32)  # 1 s of silence @ 16 kHz
        tmp = tempfile.mktemp(suffix=".wav")
        sf.write(tmp, silence, 16000)
        try:
            segs, _ = model.transcribe(tmp, language="es", vad_filter=True)
            list(segs)  # consume generator
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception as e:
        logger.debug(f"VAD warmup skipped: {e}")

    logger.info(
        f"faster-whisper model '{config.STT_MODEL}' ready in {time.time()-t0:.1f}s."
    )


# Known Whisper hallucination phrases (lowercased substrings)
_HALLUCINATION_PHRASES = [
    "gracias por ver el vídeo",
    "gracias por ver el video",
    "thanks for watching",
    "thank you for watching",
    "suscríbete",
    "subtítulos realizados",
    "subtitulos realizados",
    "las emisiones en los estados unidos",
    "amara.org",
]

# Whole-output boilerplate observed when Whisper copies the initial prompt on
# noisy or distant speech. These are intentionally matched against the complete
# normalized transcript, not as broad substrings, to avoid dropping real speech.
_PROMPT_ECHO_BOILERPLATE = [
    "conversacion en espanol entre una persona mayor y su cuidador",
    "conversacion entre una persona mayor y su cuidador",
    "conversacion en espanol",
]


def _normalize_for_hallucination_check(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def _is_near_complete_prompt_echo(text_norm: str, prompt_norm: str) -> bool:
    """Return True only when the whole transcript is essentially the prompt.

    We require both high sequence similarity and comparable length. This avoids
    filtering real patient speech that merely contains words like "conversacion
    en espanol" as part of a longer sentence.
    """
    if not text_norm or not prompt_norm:
        return False

    shorter = min(len(text_norm), len(prompt_norm))
    longer = max(len(text_norm), len(prompt_norm))
    if shorter < 12 or longer == 0:
        return False

    length_ratio = shorter / longer
    if length_ratio < 0.72:
        return False

    if text_norm == prompt_norm:
        return True

    ratio = SequenceMatcher(None, text_norm, prompt_norm).ratio()
    return ratio >= 0.90


def _is_prompt_echo(full_text: str) -> bool:
    text_norm = _normalize_for_hallucination_check(full_text)
    if not text_norm:
        return False

    prompt_norm = _normalize_for_hallucination_check(config.STT_INITIAL_PROMPT)
    candidates = [p for p in (prompt_norm, *(_PROMPT_ECHO_BOILERPLATE)) if p]
    for candidate in candidates:
        if _is_near_complete_prompt_echo(text_norm, candidate):
            logger.warning(f"Hallucination detected (prompt echo): '{full_text[:120]}'")
            return True
    return False


def _is_hallucination(segments: list, audio_duration: float | None = None) -> bool:
    """Detect residual hallucination patterns that slipped past the VAD filter."""
    if not segments:
        return False

    texts = [s["text"].strip().lower() for s in segments if s["text"].strip()]
    full_text = " ".join(texts).lower()

    if _is_prompt_echo(full_text):
        return True

    for phrase in _HALLUCINATION_PHRASES:
        if phrase in full_text:
            logger.warning(f"Hallucination detected (known phrase): '{phrase}'")
            return True

    if audio_duration and audio_duration > 0:
        for s in segments:
            if s["end"] > audio_duration * 1.5:
                logger.warning(
                    f"Hallucination detected (impossible timestamp): segment ends at "
                    f"{s['end']:.1f}s but audio is {audio_duration:.1f}s"
                )
                return True

    if len(texts) >= 4:
        counter = Counter(texts)
        most_common_text, most_common_count = counter.most_common(1)[0]
        if most_common_count >= 4 and most_common_count / len(texts) > 0.5:
            logger.warning(
                f"Hallucination detected (repetition): '{most_common_text[:80]}' "
                f"repeated {most_common_count}x"
            )
            return True
        if len(texts) >= 6 and len(counter) / len(texts) < 0.3:
            logger.warning(
                f"Hallucination detected (low diversity): only {len(counter)} unique "
                f"of {len(texts)} segments"
            )
            return True

    return False


def transcribe_audio(
    audio_path: str,
    language: str = "es",
    audio_duration: float | None = None,
) -> dict:
    """
    Transcribe an audio file and return the result dict.

    Returns: {"text": str, "language": str, "segments": list[dict]}
    Each segment: {"start": float, "end": float, "text": str}
    """
    model = _get_model()
    # The transcribe() call returns a generator; the actual work happens while
    # we iterate. Hold the lock for the full iteration so two threads can't
    # interleave GPU kernels on the shared model.
    with _model_lock:
        segments_iter, info = model.transcribe(
            audio_path,
            language=language,
            task="transcribe",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": config.STT_MIN_SILENCE_MS},
            condition_on_previous_text=False,
            no_speech_threshold=config.STT_NO_SPEECH_THRESHOLD,
            log_prob_threshold=config.STT_LOG_PROB_THRESHOLD,
            compression_ratio_threshold=config.STT_COMPRESSION_RATIO_THRESHOLD,
            initial_prompt=config.STT_INITIAL_PROMPT or None,
        )

        segments = [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
            for s in segments_iter
            if s.text and s.text.strip()
        ]

        detected_lang = getattr(info, "language", language) or language

    if _is_hallucination(segments, audio_duration):
        return {"text": "", "language": detected_lang, "segments": []}

    full_text = " ".join(s["text"] for s in segments).strip()
    return {
        "text": full_text,
        "language": detected_lang,
        "segments": segments,
    }
