import math

from src.services.episode_detector import _extract_patient_text, _extract_possible_patient_text
from src.services.memory_service import _extract_memory_lines
from src.services.speaker_id_service import (
    _active_voice_sample_vectors,
    _best_active_sample_match,
    _speaker_label,
    append_voice_sample,
    delete_voice_sample,
    list_voice_samples,
)
from src.services.tts_echo_service import normalize_tts_text


def _embedding(*values: tuple[int, float]) -> list[float]:
    vector = [0.0] * 192
    for index, value in values:
        vector[index] = value
    return vector


def test_speaker_similarity_label_boundaries():
    assert _speaker_label(0.29, threshold=0.40, uncertain_threshold=0.30) == ("OTRO", "low")
    assert _speaker_label(0.30, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE?", "uncertain")
    assert _speaker_label(0.39, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE?", "uncertain")
    assert _speaker_label(0.40, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE", "low")
    assert _speaker_label(0.55, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE", "high")


def test_inconsistent_voice_sample_is_saved_for_review_not_active():
    store = append_voice_sample(None, _embedding((0, 1.0)))
    store = append_voice_sample(store, _embedding((1, 1.0)))

    samples = list_voice_samples(store)

    assert samples[0]["active"] is True
    assert samples[0]["status"] == "active"
    assert samples[1]["active"] is False
    assert samples[1]["status"] == "review"
    assert samples[1]["consistency_similarity"] == 0.0
    assert samples[1]["reference_sample_id"] == samples[0]["id"]


def test_best_active_sample_match_ignores_review_sample_instead_of_centroiding():
    store = append_voice_sample(None, _embedding((0, 1.0)))
    store = append_voice_sample(store, _embedding((1, 1.0)))

    sample_vectors = _active_voice_sample_vectors(store)
    match = _best_active_sample_match(_embedding((0, 1.0)), sample_vectors)

    assert len(sample_vectors) == 1
    assert match["sample"]["id"] == list_voice_samples(store)[0]["id"]
    assert match["similarity"] == 1.0


def test_best_active_sample_decides_similarity_when_multiple_active_samples():
    second_sample = _embedding((0, 0.5), (1, math.sqrt(0.75)))
    store = append_voice_sample(None, _embedding((0, 1.0)))
    store = append_voice_sample(store, second_sample)

    samples = list_voice_samples(store)
    match = _best_active_sample_match(
        _embedding((1, 1.0)),
        _active_voice_sample_vectors(store),
    )

    assert [sample["active"] for sample in samples] == [True, True]
    assert match["sample"]["id"] == samples[1]["id"]
    assert math.isclose(match["similarity"], second_sample[1], rel_tol=1e-6)


def test_legacy_embedding_is_treated_as_active_sample():
    legacy = _embedding((0, 1.0))

    samples = list_voice_samples(legacy)
    match = _best_active_sample_match(legacy, _active_voice_sample_vectors(legacy))

    assert samples == [
        {
            "id": "legacy",
            "created_at": None,
            "embedding_size": 192,
            "active": True,
            "status": "active",
            "consistency_similarity": None,
            "reference_sample_id": None,
        }
    ]
    assert match["sample"]["id"] == "legacy"
    assert match["similarity"] == 1.0


def test_deleting_base_sample_recalculates_remaining_voice_sample_states():
    store = append_voice_sample(None, _embedding((0, 1.0)))
    store = append_voice_sample(store, _embedding((1, 1.0)))
    first_sample_id = list_voice_samples(store)[0]["id"]

    store = delete_voice_sample(store, first_sample_id)
    samples = list_voice_samples(store)

    assert len(samples) == 1
    assert samples[0]["active"] is True
    assert samples[0]["status"] == "active"
    assert samples[0]["consistency_similarity"] is None


def test_tag_parsers_handle_uncertain_patient():
    transcript = "[PACIENTE?] ayuda\n[OTRO] hola\n[PACIENTE] no se donde estoy\n[ASSISTANT] ya aviso"

    assert _extract_patient_text(transcript) == "no se donde estoy"
    assert _extract_possible_patient_text(transcript) == (
        "[PACIENTE?] ayuda\n[PACIENTE] no se donde estoy"
    )
    assert _extract_memory_lines(transcript) == [
        ("PACIENTE?", "ayuda"),
        ("PACIENTE", "no se donde estoy"),
        ("ASSISTANT", "ya aviso"),
    ]


def test_tts_normalization_strips_uncertain_patient_tag():
    normalized = normalize_tts_text("[PACIENTE?] Hola, ¿puedes ayudarme?")

    assert normalized == "hola puedes ayudarme"
