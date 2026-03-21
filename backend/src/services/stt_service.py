"""
Speech-to-Text service using OpenAI Whisper with CUDA acceleration.
"""

import logging
import whisper
import tempfile
import os

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


def transcribe_audio(audio_path: str, language: str = "es") -> dict:
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
    return {
        "text": result["text"].strip(),
        "language": result.get("language", language),
        "segments": segments,
    }
