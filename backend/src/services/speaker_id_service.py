"""
Speaker identification using SpeechBrain ECAPA-TDNN.

Runs fully locally (public HF model, no auth token). Produces 192-dim
embeddings with better speaker separation than Resemblyzer's 256-dim
voice encoder, so we raise the diarization threshold to 0.65.

Embeddings from the old Resemblyzer encoder (256-dim) are detected at
runtime and ignored with a warning — caregivers must re-record the voice
sample once after migrating to this stack.
"""

import logging
import subprocess
import tempfile
import threading
import os

import numpy as np
import torch
import torchaudio

from ..config import config

logger = logging.getLogger(__name__)

# Expected embedding dimensionality for the ECAPA-TDNN model we use.
EMBEDDING_DIM = 192
SAMPLE_RATE = 16000
MIN_SAMPLES = SAMPLE_RATE  # 1 s of audio is the minimum for a reliable embedding

# Model cache directory (kept out of site-packages so we can wipe/reset it).
_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models",
    "ecapa",
)

_encoder = None
_device: str | None = None
# Serializes access to the ECAPA-TDNN singleton. The underlying torch model
# runs in eval mode so inference is mostly thread-safe, but the encoder
# keeps internal buffers that we prefer not to have two threads touch at
# once (e.g. the diarization loop from routes/audio.py overlapping with a
# voice-sample upload from routes/patients.py).
_encoder_lock = threading.Lock()


def _get_device() -> str:
    global _device
    if _device is None:
        requested = config.SPEAKER_DEVICE.lower()
        if requested == "cuda" and torch.cuda.is_available():
            _device = "cuda"
        else:
            _device = "cpu"
    return _device


def _get_encoder():
    global _encoder
    if _encoder is None:
        from speechbrain.inference.speaker import EncoderClassifier
        from speechbrain.utils.fetching import LocalStrategy
        device = _get_device()
        _encoder = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=_MODEL_DIR,
            run_opts={"device": device},
            # On Windows without Developer Mode, symlinks require admin privileges.
            # COPY duplicates model files into savedir instead of symlinking.
            local_strategy=LocalStrategy.COPY,
        )
        logger.info(f"SpeechBrain ECAPA-TDNN encoder loaded on {device}.")
    return _encoder


def warmup():
    """Pre-load the ECAPA-TDNN encoder at startup."""
    _get_encoder()


def _to_wav(audio_path: str) -> str:
    """Convert any audio format to 16 kHz mono WAV via ffmpeg."""
    if audio_path.lower().endswith(".wav"):
        return audio_path
    wav_path = tempfile.mktemp(suffix=".wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", str(SAMPLE_RATE), "-ac", "1", wav_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    return wav_path


def _load_wav(audio_path: str) -> torch.Tensor:
    """Load audio as a mono float32 tensor at 16 kHz."""
    converted = _to_wav(audio_path)
    try:
        signal, sr = torchaudio.load(converted)
        if signal.shape[0] > 1:
            signal = signal.mean(dim=0, keepdim=True)
        if sr != SAMPLE_RATE:
            signal = torchaudio.functional.resample(signal, sr, SAMPLE_RATE)
        return signal.squeeze(0)  # shape: (samples,)
    finally:
        if converted != audio_path and os.path.exists(converted):
            os.unlink(converted)


def _embed(wav: torch.Tensor) -> np.ndarray:
    """Run the encoder on a 1-D tensor and return a normalized numpy vector."""
    encoder = _get_encoder()
    device = _get_device()
    if wav.dim() == 1:
        wav = wav.unsqueeze(0)  # (1, samples)
    wav = wav.to(device)
    with _encoder_lock, torch.no_grad():
        emb = encoder.encode_batch(wav).squeeze().detach().cpu().numpy()
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb.astype(np.float32)


def create_embedding(audio_path: str) -> list[float]:
    """
    Generate a 192-dim voice embedding from an audio file.
    Used when the caregiver uploads a patient voice sample.
    Returns a plain list of floats (JSON-serializable).
    """
    wav = _load_wav(audio_path)
    embedding = _embed(wav)
    return embedding.tolist()


def _check_embedding_version(patient_embedding: list[float]) -> bool:
    """
    Validate that the stored embedding matches the current encoder.
    Returns False (with a warning) for legacy Resemblyzer (256-dim) embeddings.
    """
    if len(patient_embedding) != EMBEDDING_DIM:
        logger.warning(
            f"Stored voice embedding has {len(patient_embedding)} dims but the "
            f"current encoder expects {EMBEDDING_DIM}. The patient must re-record "
            "their voice sample."
        )
        return False
    return True


def identify_speaker(
    audio_path: str,
    patient_embedding: list[float],
    threshold: float = 0.65,
) -> bool:
    """
    Compare an entire audio chunk against the stored patient embedding.
    Returns True if the speaker is likely the patient.
    """
    if not _check_embedding_version(patient_embedding):
        return False

    wav = _load_wav(audio_path)
    if wav.numel() == 0:
        return False

    chunk_embedding = _embed(wav)
    patient_emb = np.array(patient_embedding, dtype=np.float32)
    similarity = float(np.dot(chunk_embedding, patient_emb))

    match = similarity >= threshold
    clamped = max(0.0, min(1.0, similarity))
    bar = "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))
    color = "\033[92m" if match else "\033[91m"
    rst = "\033[0m"
    label = "PACIENTE" if match else "DESCONOCIDO"
    print(f"\n{color}  [SPK] SPEAKER ID: {label}{rst}")
    print(f"     Similitud: {bar} {similarity:.3f}  (umbral {threshold})")

    return match


def diarize_segments(
    audio_path: str,
    segments: list[dict],
    patient_embedding: list[float],
    threshold: float = 0.65,
) -> list[dict]:
    """
    Per-segment speaker identification.
    Takes Whisper segments [{"start", "end", "text"}] and returns them
    enriched with a "speaker" field ("PACIENTE" or "OTRO").

    For very short segments (<1 s), group them with the previous speaker
    since the embedding wouldn't be reliable (default PACIENTE because the
    patient holds the phone).
    """
    if not _check_embedding_version(patient_embedding):
        for seg in segments:
            seg["speaker"] = "OTRO"
        return segments

    wav = _load_wav(audio_path)
    patient_emb = np.array(patient_embedding, dtype=np.float32)

    print()
    last_speaker: str | None = None
    for seg in segments:
        start_sample = int(seg["start"] * SAMPLE_RATE)
        end_sample = int(seg["end"] * SAMPLE_RATE)
        seg_wav = wav[start_sample:end_sample]

        if seg_wav.numel() < MIN_SAMPLES:
            seg["speaker"] = last_speaker or "PACIENTE"
            sim_str = "---"
            tag_reason = "corto"
        else:
            seg_embedding = _embed(seg_wav)
            similarity = float(np.dot(seg_embedding, patient_emb))
            is_patient = similarity >= threshold
            seg["speaker"] = "PACIENTE" if is_patient else "OTRO"
            clamped = max(0.0, min(1.0, similarity))
            bar = "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))
            sim_str = f"{bar} {similarity:.3f}"
            tag_reason = None

        last_speaker = seg["speaker"]

        color = "\033[92m" if seg["speaker"] == "PACIENTE" else "\033[91m"
        rst = "\033[0m"
        time_range = f"{seg['start']:.1f}s-{seg['end']:.1f}s"
        extra = f" ({tag_reason})" if tag_reason else ""
        print(f"  {color}[SPK] [{seg['speaker']}]{rst} {time_range}{extra}  {sim_str}")
        print(f"     \"{seg['text'][:80]}\"")

    return segments


def build_tagged_transcript(segments: list[dict]) -> str:
    """
    Merge consecutive segments by the same speaker into blocks:
    [PACIENTE] Hola buenos días...
    [OTRO] Sé que falleció...
    """
    if not segments:
        return ""

    blocks = []
    current_speaker = segments[0].get("speaker", "OTRO")
    current_texts: list[str] = []

    for seg in segments:
        speaker = seg.get("speaker", "OTRO")
        if speaker != current_speaker:
            blocks.append(f"[{current_speaker}] {' '.join(current_texts)}")
            current_speaker = speaker
            current_texts = []
        current_texts.append(seg["text"])

    blocks.append(f"[{current_speaker}] {' '.join(current_texts)}")
    return "\n".join(blocks)
