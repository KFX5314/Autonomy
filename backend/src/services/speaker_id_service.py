"""
Speaker identification using Resemblyzer.

Compares audio against a stored patient voice embedding
to determine if the speaker is the patient or someone else.
"""

import logging
import numpy as np
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy-loaded encoder (heavy model, load once)
_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        from resemblyzer import VoiceEncoder
        _encoder = VoiceEncoder()
        logger.info("Resemblyzer VoiceEncoder loaded.")
    return _encoder


def create_embedding(audio_path: str) -> list[float]:
    """
    Generate a 256-dim voice embedding from an audio file.
    Used when the caregiver uploads a patient voice sample.
    Returns a plain list of floats (JSON-serializable).
    """
    from resemblyzer import preprocess_wav

    encoder = _get_encoder()
    wav = preprocess_wav(Path(audio_path))
    embedding = encoder.embed_utterance(wav)
    return embedding.tolist()


def identify_speaker(audio_path: str, patient_embedding: list[float], threshold: float = 0.75) -> bool:
    """
    Compare an audio chunk against the stored patient embedding.
    Returns True if the speaker is likely the patient.
    """
    from resemblyzer import preprocess_wav

    encoder = _get_encoder()
    wav = preprocess_wav(Path(audio_path))

    if len(wav) == 0:
        return False

    chunk_embedding = encoder.embed_utterance(wav)
    similarity = float(np.dot(chunk_embedding, np.array(patient_embedding)))

    match = similarity >= threshold
    bar = "█" * int(similarity * 20) + "░" * (20 - int(similarity * 20))
    color = "\033[92m" if match else "\033[91m"  # green / red
    rst = "\033[0m"
    label = "PACIENTE" if match else "DESCONOCIDO"
    print(f"\n{color}  🎤 SPEAKER ID: {label}{rst}")
    print(f"     Similitud: {bar} {similarity:.3f}  (umbral {threshold})")

    return match
