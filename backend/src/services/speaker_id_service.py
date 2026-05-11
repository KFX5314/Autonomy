"""
Speaker identification using SpeechBrain ECAPA-TDNN.

Runs fully locally (public HF model, no auth token). Produces 192-dim
embeddings with better speaker separation than Resemblyzer's 256-dim
voice encoder.

Embeddings from the old Resemblyzer encoder (256-dim) are detected at
runtime and ignored with a warning — caregivers must re-record the voice
sample once after migrating to this stack.
"""

import logging
import subprocess
import tempfile
import threading
import os
import uuid
from datetime import datetime, timezone

import numpy as np
import torch
import torchaudio

from ..config import config

logger = logging.getLogger(__name__)

# Expected embedding dimensionality for the ECAPA-TDNN model we use.
EMBEDDING_DIM = 192
SAMPLE_RATE = 16000
MIN_SAMPLES = SAMPLE_RATE  # 1 s of audio is the minimum for a reliable embedding
MIN_ENROLLMENT_SPEECH_SAMPLES = SAMPLE_RATE * 3
MAX_VOICE_SAMPLES = 10

# Diarization similarity threshold for ECAPA-TDNN embeddings.
# 0.40 allows for natural variations in speech or microphone distance.
DIARIZATION_THRESHOLD = config.SPEAKER_DIARIZATION_THRESHOLD
LOW_CONFIDENCE_MARGIN = 0.08

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


def _speaker_confidence(similarity: float, threshold: float) -> str:
    return "low" if abs(similarity - threshold) <= LOW_CONFIDENCE_MARGIN else "high"


def _similarity_bar(similarity: float) -> str:
    clamped = max(0.0, min(1.0, similarity))
    return "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))


def create_embedding(audio_path: str) -> list[float]:
    """
    Generate a 192-dim voice embedding from an audio file.
    Used when the caregiver uploads a patient voice sample.
    Uses Whisper's VAD to strip silence before embedding to ensure
    the reference embedding isn't polluted by background noise.
    Returns a plain list of floats (JSON-serializable).
    """
    from .stt_service import transcribe_audio

    # Run VAD to find actual speech segments
    res = transcribe_audio(audio_path)
    segments = res.get("segments", [])

    wav = _load_wav(audio_path)

    if segments:
        speech_chunks = []
        for seg in segments:
            start_sample = int(seg["start"] * SAMPLE_RATE)
            end_sample = int(seg["end"] * SAMPLE_RATE)
            speech_chunks.append(wav[start_sample:end_sample])
        if speech_chunks:
            filtered_wav = torch.cat(speech_chunks)
            speech_seconds = filtered_wav.numel() / SAMPLE_RATE
            if filtered_wav.numel() >= MIN_SAMPLES:
                wav = filtered_wav
                if filtered_wav.numel() < MIN_ENROLLMENT_SPEECH_SAMPLES:
                    logger.warning(
                        "Voice sample has only %.1fs of detected speech. "
                        "For better diarization, record a clean 10-20s sample.",
                        speech_seconds,
                    )
            else:
                raise ValueError(
                    "Voice sample is too short after VAD. Record at least 3 seconds "
                    "of clear patient speech, ideally 10-20 seconds."
                )
    elif wav.numel() < MIN_ENROLLMENT_SPEECH_SAMPLES:
        logger.warning(
            "Voice sample has only %.1fs total audio. For better diarization, "
            "record a clean 10-20s sample.",
            wav.numel() / SAMPLE_RATE,
        )

    embedding = _embed(wav)
    return embedding.tolist()


def _is_valid_embedding(embedding: object) -> bool:
    if not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM:
        return False
    try:
        np.array(embedding, dtype=np.float32)
    except (TypeError, ValueError):
        return False
    return True


def _voice_samples_from_store(voice_embedding: object) -> list[dict]:
    """Return normalized sample dicts from legacy or multi-sample storage."""
    if _is_valid_embedding(voice_embedding):
        return [{
            "id": "legacy",
            "created_at": None,
            "embedding": voice_embedding,
        }]

    if isinstance(voice_embedding, dict):
        samples = voice_embedding.get("samples", [])
        if isinstance(samples, list):
            return [
                s for s in samples
                if isinstance(s, dict) and _is_valid_embedding(s.get("embedding"))
            ]
    return []


def list_voice_samples(voice_embedding: object) -> list[dict]:
    """Return caregiver-safe metadata for stored voice samples."""
    return [
        {
            "id": str(sample.get("id") or "legacy"),
            "created_at": sample.get("created_at"),
            "embedding_size": len(sample.get("embedding") or []),
        }
        for sample in _voice_samples_from_store(voice_embedding)
    ]


def append_voice_sample(voice_embedding: object, embedding: list[float]) -> dict:
    """Add a voice sample and keep only the most recent MAX_VOICE_SAMPLES."""
    samples = _voice_samples_from_store(voice_embedding)
    samples.append({
        "id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding": embedding,
    })
    samples = samples[-MAX_VOICE_SAMPLES:]
    return {"samples": samples}


def delete_voice_sample(voice_embedding: object, sample_id: str) -> dict | None:
    samples = [
        sample for sample in _voice_samples_from_store(voice_embedding)
        if str(sample.get("id") or "legacy") != sample_id
    ]
    if not samples:
        return None
    return {"samples": samples[-MAX_VOICE_SAMPLES:]}


def _average_patient_embedding(voice_embedding: object) -> np.ndarray | None:
    """
    Resolve legacy or multi-sample storage to one normalized patient vector.

    Embeddings are already normalized when created. We normalize again before
    averaging so legacy/manual records cannot skew the centroid by magnitude.
    """
    vectors = []
    for sample in _voice_samples_from_store(voice_embedding):
        emb = np.array(sample["embedding"], dtype=np.float32)
        norm = np.linalg.norm(emb)
        if norm > 0:
            vectors.append(emb / norm)

    if not vectors:
        if isinstance(voice_embedding, list):
            logger.warning(
                f"Stored voice embedding has {len(voice_embedding)} dims but the "
                f"current encoder expects {EMBEDDING_DIM}. The patient must re-record "
                "their voice sample."
            )
        return None

    centroid = np.mean(vectors, axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm
    return centroid.astype(np.float32)


def _check_embedding_version(patient_embedding: object) -> bool:
    """Validate that at least one stored embedding matches the current encoder."""
    if _average_patient_embedding(patient_embedding) is None:
        logger.warning(
            "No valid ECAPA-TDNN voice samples available for speaker verification."
        )
        return False
    return True


def identify_speaker(
    audio_path: str,
    patient_embedding: object,
    threshold: float = DIARIZATION_THRESHOLD,
) -> bool:
    """
    Compare an entire audio chunk against the stored patient embedding.
    Returns True if the speaker is likely the patient.
    """
    patient_emb = _average_patient_embedding(patient_embedding)
    if patient_emb is None:
        return False

    wav = _load_wav(audio_path)
    if wav.numel() == 0:
        return False

    chunk_embedding = _embed(wav)
    similarity = float(np.dot(chunk_embedding, patient_emb))

    match = similarity >= threshold
    clamped = max(0.0, min(1.0, similarity))
    bar = "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))
    color = "\033[92m" if match else "\033[91m"
    rst = "\033[0m"
    label = "PACIENTE" if match else "DESCONOCIDO"
    bar = _similarity_bar(similarity)
    confidence = _speaker_confidence(similarity, threshold)
    print(f"\n{color}  [SPK] SPEAKER ID: {label}{rst}")
    print(f"     Similitud: {bar} {similarity:.3f}  (umbral {threshold}, confianza {confidence})")

    return match


def _expanded_segment_wav(wav: torch.Tensor, segments: list[dict], index: int) -> tuple[torch.Tensor, bool]:
    """Expand a short segment with neighboring Whisper segments when needed."""
    seg = segments[index]
    start_sample = int(seg["start"] * SAMPLE_RATE)
    end_sample = int(seg["end"] * SAMPLE_RATE)
    if end_sample - start_sample >= MIN_SAMPLES:
        return wav[start_sample:end_sample], False

    left = index - 1
    right = index + 1
    expanded_start = start_sample
    expanded_end = end_sample
    while expanded_end - expanded_start < MIN_SAMPLES and (left >= 0 or right < len(segments)):
        if left >= 0:
            expanded_start = min(expanded_start, int(segments[left]["start"] * SAMPLE_RATE))
            left -= 1
            if expanded_end - expanded_start >= MIN_SAMPLES:
                break
        if right < len(segments):
            expanded_end = max(expanded_end, int(segments[right]["end"] * SAMPLE_RATE))
            right += 1

    expanded_start = max(0, expanded_start)
    expanded_end = min(wav.numel(), expanded_end)
    return wav[expanded_start:expanded_end], True


def diarize_segments(
    audio_path: str,
    segments: list[dict],
    patient_embedding: object,
    threshold: float = DIARIZATION_THRESHOLD,
) -> list[dict]:
    """
    Per-segment speaker identification.
    Takes Whisper segments [{"start", "end", "text"}] and returns them
    enriched with a "speaker" field ("PACIENTE" or "OTRO").

    Very short segments are expanded with neighboring Whisper segments before
    embedding; if they are still too short, they inherit the previous speaker.
    """
    patient_emb = _average_patient_embedding(patient_embedding)
    if patient_emb is None:
        for seg in segments:
            seg["speaker"] = "OTRO"
            seg["speaker_similarity"] = None
            seg["speaker_confidence"] = "unavailable"
        return segments

    wav = _load_wav(audio_path)

    print()
    last_speaker: str | None = None
    for index, seg in enumerate(segments):
        seg_wav, expanded = _expanded_segment_wav(wav, segments, index)

        if seg_wav.numel() < MIN_SAMPLES:
            seg["speaker"] = last_speaker or "PACIENTE"
            seg["speaker_similarity"] = None
            seg["speaker_confidence"] = "inherited"
            sim_str = "---"
            tag_reason = "corto"
        else:
            seg_embedding = _embed(seg_wav)
            similarity = float(np.dot(seg_embedding, patient_emb))
            is_patient = similarity >= threshold
            confidence = _speaker_confidence(similarity, threshold)
            seg["speaker"] = "PACIENTE" if is_patient else "OTRO"
            seg["speaker_similarity"] = similarity
            seg["speaker_threshold"] = threshold
            seg["speaker_confidence"] = confidence
            clamped = max(0.0, min(1.0, similarity))
            bar = "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))
            bar = _similarity_bar(similarity)
            sim_str = f"{bar} {similarity:.3f} {confidence}"
            tag_reason = "agregado" if expanded else None

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
