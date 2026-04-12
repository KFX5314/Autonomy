"""
Speech-to-Text service using faster-whisper with CUDA acceleration.

faster-whisper bundles silero-vad via ``vad_filter=True``: non-speech regions
are trimmed *before* decoding, which removes the vast majority of Whisper
hallucinations on silence (no more "Gracias por ver el vídeo" etc.).
The legacy phrase/timestamp/repetition filter is kept as a cheap safety net.
"""

import logging
import time
import tempfile
import os
from collections import Counter

from faster_whisper import WhisperModel

from ..config import config

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None


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


def _is_hallucination(segments: list, audio_duration: float | None = None) -> bool:
    """Detect residual hallucination patterns that slipped past the VAD filter."""
    if not segments:
        return False

    texts = [s["text"].strip().lower() for s in segments if s["text"].strip()]
    full_text = " ".join(texts).lower()

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
    segments_iter, info = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
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
