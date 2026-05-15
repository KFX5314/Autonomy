from src.services import stt_service


def _segments(text: str) -> list[dict]:
    return [{"start": 0.0, "end": 1.0, "text": text}]


def test_prompt_echo_hallucination_is_filtered(monkeypatch):
    monkeypatch.setattr(
        stt_service.config,
        "STT_INITIAL_PROMPT",
        "Conversación en español entre una persona mayor y su cuidador.",
    )

    assert stt_service._is_hallucination(
        _segments("Conversación en español entre una persona mayor y su cuidador.")
    )


def test_prompt_echo_filter_handles_accents_and_punctuation(monkeypatch):
    monkeypatch.setattr(
        stt_service.config,
        "STT_INITIAL_PROMPT",
        "Conversación en español entre una persona mayor y su cuidador.",
    )

    assert stt_service._is_hallucination(
        _segments("Conversacion en espanol entre una persona mayor y su cuidador")
    )


def test_observed_boilerplate_variant_is_filtered_when_prompt_is_empty(monkeypatch):
    monkeypatch.setattr(stt_service.config, "STT_INITIAL_PROMPT", "")

    assert stt_service._is_hallucination(
        _segments("Conversación entre una persona mayor y su cuidador.")
    )


def test_real_sentence_containing_similar_words_is_not_filtered(monkeypatch):
    monkeypatch.setattr(
        stt_service.config,
        "STT_INITIAL_PROMPT",
        "Conversación en español entre una persona mayor y su cuidador.",
    )

    assert not stt_service._is_hallucination(
        _segments(
            "María dijo que había una conversación en español en la televisión "
            "y luego pidió un vaso de agua."
        )
    )


def test_long_real_sentence_with_prompt_words_is_not_filtered(monkeypatch):
    monkeypatch.setattr(
        stt_service.config,
        "STT_INITIAL_PROMPT",
        "Conversación en español entre una persona mayor y su cuidador.",
    )

    assert not stt_service._is_hallucination(
        _segments(
            "Escuché una conversación en español entre una persona mayor y su "
            "cuidador en la sala, pero ahora quiero llamar a mi hija."
        )
    )
