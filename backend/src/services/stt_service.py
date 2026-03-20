"""
Speech-to-Text service using OpenAI Whisper with CUDA acceleration.
"""

import whisper
import tempfile
import os

from ..config import config

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = whisper.load_model(config.STT_MODEL, device=config.STT_DEVICE)
    return _model


def transcribe_audio(audio_path: str, language: str = "es") -> dict:
    """
    Transcribe an audio file and return the result dict.
    Returns: {"text": str, "language": str}
    """
    model = _get_model()
    result = model.transcribe(audio_path, language=language, task="transcribe")
    return {
        "text": result["text"].strip(),
        "language": result.get("language", language),
    }
