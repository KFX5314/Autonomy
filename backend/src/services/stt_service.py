"""
Speech-to-Text service using OpenAI Whisper with CUDA acceleration.
"""

import logging
import whisper
import tempfile
import os
from collections import Counter

from ..config import config

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = whisper.load_model(config.STT_MODEL, device=config.STT_DEVICE)
    return _model


def warmup():
    """Pre-download and load the Whisper model at startup."""
    logger.info(f"Loading Whisper model '{config.STT_MODEL}' on {config.STT_DEVICE}...")
    import time
    t0 = time.time()
    _get_model()
    logger.info(f"Whisper model '{config.STT_MODEL}' ready in {time.time()-t0:.1f}s.")


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


def _is_hallucination(segments: list, audio_duration: float | None = None) -> bool:
    """Detect Whisper hallucination patterns (repetitive text, known phantom phrases, impossible timestamps)."""
    if not segments:
        return False

    texts = [s["text"].strip().lower() for s in segments if s["text"].strip()]
    full_text = " ".join(texts).lower()

    # 1. Known hallucination phrases
    for phrase in _HALLUCINATION_PHRASES:
        if phrase in full_text:
            logger.warning(f"Hallucination detected (known phrase): '{phrase}'")
            return True

    # 2. Impossible timestamps: segment end far beyond audio duration
    if audio_duration and audio_duration > 0:
        for s in segments:
            if s["end"] > audio_duration * 1.5:  # segment extends >50% beyond actual audio
                logger.warning(f"Hallucination detected (impossible timestamp): segment ends at {s['end']:.1f}s but audio is {audio_duration:.1f}s")
                return True

    # 3. Repetition detection (needs 4+ segments)
    if len(texts) >= 4:
        counter = Counter(texts)
        most_common_text, most_common_count = counter.most_common(1)[0]
        if most_common_count >= 4 and most_common_count / len(texts) > 0.5:
            logger.warning(f"Hallucination detected (repetition): '{most_common_text[:80]}' repeated {most_common_count}x")
            return True
        if len(texts) >= 6 and len(counter) / len(texts) < 0.3:
            logger.warning(f"Hallucination detected (low diversity): only {len(counter)} unique of {len(texts)} segments")
            return True

    return False


def transcribe_audio(audio_path: str, language: str = "es", audio_duration: float | None = None) -> dict:
    """
    Transcribe an audio file and return the result dict.
    Returns: {"text": str, "language": str, "segments": list[dict]}
    Each segment: {"start": float, "end": float, "text": str}
    """
    model = _get_model()
    result = model.transcribe(audio_path, language=language, task="transcribe")
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in result.get("segments", [])
        if s["text"].strip()
    ]
    # Reject hallucinated output
    if _is_hallucination(segments, audio_duration):
        return {"text": "", "language": result.get("language", language), "segments": []}
    return {
        "text": result["text"].strip(),
        "language": result.get("language", language),
        "segments": segments,
    }
