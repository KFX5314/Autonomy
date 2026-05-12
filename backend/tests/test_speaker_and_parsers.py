from src.services.episode_detector import _extract_patient_text, _extract_possible_patient_text
from src.services.memory_service import _extract_memory_lines
from src.services.speaker_id_service import _speaker_label
from src.services.tts_echo_service import normalize_tts_text


def test_speaker_similarity_label_boundaries():
    assert _speaker_label(0.29, threshold=0.40, uncertain_threshold=0.30) == ("OTRO", "low")
    assert _speaker_label(0.30, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE?", "uncertain")
    assert _speaker_label(0.39, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE?", "uncertain")
    assert _speaker_label(0.40, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE", "low")
    assert _speaker_label(0.55, threshold=0.40, uncertain_threshold=0.30) == ("PACIENTE", "high")


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
