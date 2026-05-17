"""
Speaker identification using SpeechBrain ECAPA-TDNN.

Runs fully locally with SpeechBrain's public ECAPA model and stores
192-dimensional embeddings for patient voice matching.
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

# ECAPA-TDNN model constants.
EMBEDDING_DIM = 192
SAMPLE_RATE = 16000
MIN_SAMPLES = SAMPLE_RATE  # 1 s of audio is the minimum for a reliable embedding
MIN_ENROLLMENT_SPEECH_SAMPLES = SAMPLE_RATE * 3
MAX_VOICE_SAMPLES = 10

# Similarity thresholds for patient and possible-patient labels.
DIARIZATION_THRESHOLD = config.SPEAKER_DIARIZATION_THRESHOLD
UNCERTAIN_THRESHOLD = config.SPEAKER_UNCERTAIN_THRESHOLD
SAMPLE_CONSISTENCY_THRESHOLD = config.SPEAKER_SAMPLE_CONSISTENCY_THRESHOLD
LOW_CONFIDENCE_MARGIN = 0.08
VOICE_SAMPLE_STATUS_ACTIVE = "active"
VOICE_SAMPLE_STATUS_REVIEW = "review"
VOICE_REFERENCE_STRATEGY = "best_active_sample"

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


def _load_wav_with_soundfile(audio_path: str) -> tuple[torch.Tensor, int]:
    """Fallback loader for torchaudio builds that require torchcodec."""
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "soundfile is required as an audio loading fallback. "
            "Install backend requirements again."
        ) from exc

    data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
    # soundfile returns (samples, channels); torchaudio returns (channels, samples).
    signal = torch.from_numpy(data.T.copy())
    return signal, sr


def _load_wav(audio_path: str) -> torch.Tensor:
    """Load audio as a mono float32 tensor at 16 kHz."""
    converted = _to_wav(audio_path)
    try:
        try:
            signal, sr = torchaudio.load(converted)
        except (ImportError, RuntimeError, OSError) as exc:
            logger.warning(
                "torchaudio.load failed for %s; falling back to soundfile: %s",
                converted,
                exc,
            )
            signal, sr = _load_wav_with_soundfile(converted)
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


def _speaker_label(similarity: float, threshold: float, uncertain_threshold: float) -> tuple[str, str]:
    if similarity >= threshold:
        return "PACIENTE", _speaker_confidence(similarity, threshold)
    if similarity >= uncertain_threshold:
        return "PACIENTE?", "uncertain"
    return "OTRO", _speaker_confidence(similarity, uncertain_threshold)


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


def _embedding_array(embedding: object) -> np.ndarray | None:
    try:
        arr = np.asarray(embedding, dtype=np.float32).reshape(-1)
    except (TypeError, ValueError):
        return None
    if arr.shape[0] != EMBEDDING_DIM or not np.all(np.isfinite(arr)):
        return None
    return arr


def _is_valid_embedding(embedding: object) -> bool:
    if not isinstance(embedding, list):
        return False
    return _embedding_array(embedding) is not None


def _normalize_embedding(embedding: object) -> np.ndarray | None:
    arr = _embedding_array(embedding)
    if arr is None:
        return None
    norm = np.linalg.norm(arr)
    if norm <= 0:
        return None
    return (arr / norm).astype(np.float32)


def _voice_sample_sort_key(index_and_sample: tuple[int, dict]) -> tuple[bool, str, int]:
    index, sample = index_and_sample
    created_at = sample.get("created_at")
    return (created_at is not None, str(created_at or ""), index)


def _sort_voice_samples(samples: list[dict]) -> list[dict]:
    return [
        sample
        for _, sample in sorted(enumerate(samples), key=_voice_sample_sort_key)
    ]


def _has_voice_sample_state(sample: dict) -> bool:
    active = sample.get("active")
    status = sample.get("status")
    return (
        isinstance(active, bool)
        and status in {VOICE_SAMPLE_STATUS_ACTIVE, VOICE_SAMPLE_STATUS_REVIEW}
        and (
            (active and status == VOICE_SAMPLE_STATUS_ACTIVE)
            or (not active and status == VOICE_SAMPLE_STATUS_REVIEW)
        )
        and "consistency_similarity" in sample
        and "reference_sample_id" in sample
    )


def _recalculate_voice_sample_states(
    samples: list[dict],
    consistency_threshold: float = SAMPLE_CONSISTENCY_THRESHOLD,
) -> list[dict]:
    """Mark samples active only when they agree with already accepted samples."""
    recalculated: list[dict] = []
    active_vectors: list[tuple[dict, np.ndarray]] = []

    for sample in _sort_voice_samples(samples):
        next_sample = dict(sample)
        next_sample["active"] = False
        next_sample["status"] = VOICE_SAMPLE_STATUS_REVIEW
        next_sample["consistency_similarity"] = None
        next_sample["reference_sample_id"] = None

        emb = _normalize_embedding(next_sample.get("embedding"))
        if emb is None:
            recalculated.append(next_sample)
            continue

        if not active_vectors:
            next_sample["active"] = True
            next_sample["status"] = VOICE_SAMPLE_STATUS_ACTIVE
            active_vectors.append((next_sample, emb))
            recalculated.append(next_sample)
            continue

        best_sample: dict | None = None
        best_similarity = -1.0
        for active_sample, active_emb in active_vectors:
            similarity = float(np.dot(emb, active_emb))
            if similarity > best_similarity:
                best_similarity = similarity
                best_sample = active_sample

        next_sample["consistency_similarity"] = best_similarity
        if best_sample is not None:
            next_sample["reference_sample_id"] = str(best_sample.get("id") or "sample")

        if best_similarity >= consistency_threshold:
            next_sample["active"] = True
            next_sample["status"] = VOICE_SAMPLE_STATUS_ACTIVE
            active_vectors.append((next_sample, emb))

        recalculated.append(next_sample)

    return recalculated


def _voice_samples_from_store(voice_embedding: object) -> list[dict]:
    """Return normalized sample dicts from the multi-sample storage shape."""
    if isinstance(voice_embedding, dict):
        samples = voice_embedding.get("samples", [])
        if isinstance(samples, list):
            valid_samples = []
            for index, sample in enumerate(samples):
                if not isinstance(sample, dict) or not _is_valid_embedding(sample.get("embedding")):
                    continue
                normalized = dict(sample)
                normalized["id"] = str(normalized.get("id") or f"sample-{index + 1}")
                normalized["created_at"] = normalized.get("created_at")
                valid_samples.append(normalized)
            valid_samples = _sort_voice_samples(valid_samples)[-MAX_VOICE_SAMPLES:]
            if any(not _has_voice_sample_state(sample) for sample in valid_samples):
                return _recalculate_voice_sample_states(valid_samples)
            return valid_samples
    return []


def list_voice_samples(voice_embedding: object) -> list[dict]:
    """Return caregiver-safe metadata for stored voice samples."""
    return [
        {
            "id": str(sample.get("id") or "sample"),
            "created_at": sample.get("created_at"),
            "embedding_size": len(sample.get("embedding") or []),
            "active": bool(sample.get("active")),
            "status": sample.get("status") or VOICE_SAMPLE_STATUS_REVIEW,
            "consistency_similarity": sample.get("consistency_similarity"),
            "reference_sample_id": sample.get("reference_sample_id"),
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
    samples = _sort_voice_samples(samples)[-MAX_VOICE_SAMPLES:]
    return {"samples": _recalculate_voice_sample_states(samples)}


def delete_voice_sample(voice_embedding: object, sample_id: str) -> dict | None:
    samples = [
        sample for sample in _voice_samples_from_store(voice_embedding)
        if str(sample.get("id") or "sample") != sample_id
    ]
    if not samples:
        return None
    samples = _sort_voice_samples(samples)[-MAX_VOICE_SAMPLES:]
    return {"samples": _recalculate_voice_sample_states(samples)}


def _active_voice_sample_vectors(voice_embedding: object) -> list[tuple[dict, np.ndarray]]:
    """Return active sample records paired with normalized embeddings."""
    vectors: list[tuple[dict, np.ndarray]] = []
    for sample in _voice_samples_from_store(voice_embedding):
        if sample.get("active") is not True or sample.get("status") != VOICE_SAMPLE_STATUS_ACTIVE:
            continue
        emb = _normalize_embedding(sample.get("embedding"))
        if emb is not None:
            vectors.append((sample, emb))

    return vectors


def _best_active_sample_match(
    candidate_embedding: object,
    sample_vectors: list[tuple[dict, np.ndarray]],
) -> dict | None:
    candidate = _normalize_embedding(candidate_embedding)
    if candidate is None or not sample_vectors:
        return None

    best_sample: dict | None = None
    best_similarity = -1.0
    for sample, sample_emb in sample_vectors:
        similarity = float(np.dot(candidate, sample_emb))
        if similarity > best_similarity:
            best_similarity = similarity
            best_sample = sample

    if best_sample is None:
        return None
    return {"sample": best_sample, "similarity": best_similarity}


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
    uncertain_threshold: float = UNCERTAIN_THRESHOLD,
) -> list[dict]:
    """
    Per-segment speaker identification.
    Takes Whisper segments [{"start", "end", "text"}] and returns them
    enriched with a "speaker" field ("PACIENTE", "PACIENTE?" or "OTRO").

    Very short segments are expanded with neighboring Whisper segments before
    embedding; if they are still too short, they inherit the previous speaker.
    """
    sample_vectors = _active_voice_sample_vectors(patient_embedding)
    if not sample_vectors:
        for seg in segments:
            seg["speaker"] = "OTRO"
            seg["speaker_similarity"] = None
            seg["speaker_confidence"] = "unavailable"
            seg["speaker_sample_id"] = None
            seg["speaker_reference_strategy"] = VOICE_REFERENCE_STRATEGY
        return segments

    wav = _load_wav(audio_path)

    print()
    last_speaker: str | None = None
    for index, seg in enumerate(segments):
        seg_wav, expanded = _expanded_segment_wav(wav, segments, index)

        if seg_wav.numel() < MIN_SAMPLES:
            seg["speaker"] = last_speaker or "PACIENTE?"
            seg["speaker_similarity"] = None
            seg["speaker_confidence"] = "inherited" if last_speaker else "uncertain"
            seg["speaker_sample_id"] = None
            seg["speaker_reference_strategy"] = VOICE_REFERENCE_STRATEGY
            sim_str = "---"
            tag_reason = "corto"
        else:
            seg_embedding = _embed(seg_wav)
            match_info = _best_active_sample_match(seg_embedding, sample_vectors)
            if match_info is None:
                similarity = -1.0
                sample_id = None
            else:
                similarity = float(match_info["similarity"])
                sample = match_info["sample"]
                sample_id = str(sample.get("id") or "sample")
            speaker, confidence = _speaker_label(similarity, threshold, uncertain_threshold)
            seg["speaker"] = speaker
            seg["speaker_similarity"] = similarity
            seg["speaker_threshold"] = threshold
            seg["speaker_uncertain_threshold"] = uncertain_threshold
            seg["speaker_confidence"] = confidence
            seg["speaker_sample_id"] = sample_id
            seg["speaker_reference_strategy"] = VOICE_REFERENCE_STRATEGY
            clamped = max(0.0, min(1.0, similarity))
            bar = "█" * int(clamped * 20) + "░" * (20 - int(clamped * 20))
            bar = _similarity_bar(similarity)
            sim_str = f"{bar} {similarity:.3f} {confidence}"
            tag_reason = "agregado" if expanded else None

        last_speaker = seg["speaker"]

        if seg["speaker"] == "PACIENTE":
            color = "\033[92m"
        elif seg["speaker"] == "PACIENTE?":
            color = "\033[93m"
        else:
            color = "\033[91m"
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
    [PACIENTE?] Puede que sea María...
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
