"""
Speaker identification using Resemblyzer.

Compares audio against a stored patient voice embedding
to determine if the speaker is the patient or someone else.
Supports per-segment diarization within a single audio chunk.
"""

import logging
import numpy as np
import subprocess
import tempfile
import os
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


def warmup():
    """Pre-load the Resemblyzer VoiceEncoder at startup."""
    _get_encoder()


def _to_wav(audio_path: str) -> str:
    """Convert any audio format to 16kHz mono WAV via ffmpeg. Returns path to temp WAV."""
    if audio_path.lower().endswith(".wav"):
        return audio_path
    wav_path = tempfile.mktemp(suffix=".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    return wav_path


def _load_wav(audio_path: str):
    """Load and preprocess audio, return wav_array at 16kHz."""
    from resemblyzer import preprocess_wav
    converted = _to_wav(audio_path)
    try:
        return preprocess_wav(Path(converted))
    finally:
        if converted != audio_path:
            os.unlink(converted)


def create_embedding(audio_path: str) -> list[float]:
    """
    Generate a 256-dim voice embedding from an audio file.
    Used when the caregiver uploads a patient voice sample.
    Returns a plain list of floats (JSON-serializable).
    """
    encoder = _get_encoder()
    wav = _load_wav(audio_path)
    embedding = encoder.embed_utterance(wav)
    return embedding.tolist()


def identify_speaker(audio_path: str, patient_embedding: list[float], threshold: float = 0.75) -> bool:
    """
    Compare an entire audio chunk against the stored patient embedding.
    Returns True if the speaker is likely the patient.
    """
    encoder = _get_encoder()
    wav = _load_wav(audio_path)

    if len(wav) == 0:
        return False

    chunk_embedding = encoder.embed_utterance(wav)
    similarity = float(np.dot(chunk_embedding, np.array(patient_embedding)))

    match = similarity >= threshold
    bar = "█" * int(similarity * 20) + "░" * (20 - int(similarity * 20))
    color = "\033[92m" if match else "\033[91m"
    rst = "\033[0m"
    label = "PACIENTE" if match else "DESCONOCIDO"
    print(f"\n{color}  🎤 SPEAKER ID: {label}{rst}")
    print(f"     Similitud: {bar} {similarity:.3f}  (umbral {threshold})")

    return match


def diarize_segments(
    audio_path: str,
    segments: list[dict],
    patient_embedding: list[float],
    threshold: float = 0.60,
) -> list[dict]:
    """
    Per-segment speaker identification.
    Takes Whisper segments [{"start", "end", "text"}] and returns them
    enriched with a "speaker" field ("PACIENTE" or "OTRO").

    For very short segments (<1s of audio), groups them with the previous
    segment's speaker since the embedding wouldn't be reliable.
    """
    encoder = _get_encoder()
    wav = _load_wav(audio_path)
    sr = 16000  # resemblyzer preprocesses to 16kHz
    patient_emb = np.array(patient_embedding)

    MIN_SAMPLES = sr  # 1 second minimum for a reliable embedding

    print()
    last_speaker = None
    for seg in segments:
        start_sample = int(seg["start"] * sr)
        end_sample = int(seg["end"] * sr)
        seg_wav = wav[start_sample:end_sample]

        if len(seg_wav) < MIN_SAMPLES:
            # Too short — inherit from last speaker or default to PACIENTE
            # (patient holds the phone, so most short utterances are theirs)
            seg["speaker"] = last_speaker or "PACIENTE"
            sim_str = "---"
            tag_reason = "corto"
        else:
            seg_embedding = encoder.embed_utterance(seg_wav)
            similarity = float(np.dot(seg_embedding, patient_emb))
            is_patient = similarity >= threshold

            seg["speaker"] = "PACIENTE" if is_patient else "OTRO"
            bar = "█" * int(similarity * 20) + "░" * (20 - int(similarity * 20))
            sim_str = f"{bar} {similarity:.3f}"
            tag_reason = None

        last_speaker = seg["speaker"]

        # Debug print
        color = "\033[92m" if seg["speaker"] == "PACIENTE" else "\033[91m"
        rst = "\033[0m"
        time_range = f"{seg['start']:.1f}s-{seg['end']:.1f}s"
        extra = f" ({tag_reason})" if tag_reason else ""
        print(f"  {color}🎤 [{seg['speaker']}]{rst} {time_range}{extra}  {sim_str}")
        print(f"     \"{seg['text'][:80]}\"")

    return segments


def build_tagged_transcript(segments: list[dict]) -> str:
    """
    Merge consecutive segments by the same speaker into blocks, producing:
    [PACIENTE] Hola buenos días...
    [OTRO] Sé que falleció...
    """
    if not segments:
        return ""

    blocks = []
    current_speaker = segments[0].get("speaker", "OTRO")
    current_texts = []

    for seg in segments:
        speaker = seg.get("speaker", "OTRO")
        if speaker != current_speaker:
            blocks.append(f"[{current_speaker}] {' '.join(current_texts)}")
            current_speaker = speaker
            current_texts = []
        current_texts.append(seg["text"])

    blocks.append(f"[{current_speaker}] {' '.join(current_texts)}")
    return "\n".join(blocks)
