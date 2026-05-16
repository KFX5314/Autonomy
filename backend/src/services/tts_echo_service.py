"""Helpers for recognizing the app's own spoken TTS in later mic chunks."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from ..config import config


_TAG_RE = re.compile(r"\[(?:PACIENTE\?|PACIENTE|OTRO|ASISTENTE)\]\s*", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class TtsEchoMatch:
    ratio: float
    recent_tts_age_ms: int


def normalize_tts_text(text: str) -> str:
    """Normalize text enough for robust STT-vs-TTS echo matching."""
    text = _TAG_RE.sub(" ", text or "")
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return _SPACE_RE.sub(" ", text).strip()


def detect_tts_echo(
    transcript_text: str,
    recent_tts_text: str | None,
    recent_tts_age_ms: int | None,
) -> TtsEchoMatch | None:
    """Return a match when a transcript is likely leaked assistant TTS.

    The client is trusted only as a hint: the current transcript must still be
    a strong text match to the recent TTS string and the metadata must be fresh.
    """
    if not recent_tts_text or recent_tts_age_ms is None:
        return None
    if recent_tts_age_ms < 0 or recent_tts_age_ms > config.TTS_ECHO_MATCH_WINDOW_MS:
        return None

    transcript_norm = normalize_tts_text(transcript_text)
    tts_norm = normalize_tts_text(recent_tts_text)
    min_chars = config.TTS_ECHO_MIN_CHARS
    if len(transcript_norm) < min_chars or len(tts_norm) < min_chars:
        return None

    ratio = SequenceMatcher(None, transcript_norm, tts_norm).ratio()
    if transcript_norm == tts_norm:
        ratio = 1.0
    elif transcript_norm in tts_norm or tts_norm in transcript_norm:
        shorter = min(len(transcript_norm), len(tts_norm))
        longer = max(len(transcript_norm), len(tts_norm))
        coverage = shorter / longer if longer else 0.0
        if coverage >= 0.75:
            ratio = 1.0

    if ratio >= config.TTS_ECHO_MATCH_RATIO:
        return TtsEchoMatch(ratio=ratio, recent_tts_age_ms=recent_tts_age_ms)
    return None


def tag_as_assistant(transcript_text: str) -> str:
    text = _TAG_RE.sub(" ", transcript_text or "")
    text = _SPACE_RE.sub(" ", text).strip()
    return f"[ASISTENTE] {text}" if text else "[ASISTENTE]"
