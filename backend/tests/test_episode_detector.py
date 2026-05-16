import pytest

from src.services.episode_detector import (
    EpisodeDetector,
    _build_analysis_prompt,
    _extract_patient_text,
    _extract_possible_patient_text,
    _extract_rule_patient_text,
)


def test_help_word_triggers_episode():
    result = EpisodeDetector({})._rule_based_check("necesito ayuda")

    assert result is not None
    assert result.is_episode is True
    assert result.severity == 5


def test_configured_phrase_and_regex_trigger_episode():
    detector = EpisodeDetector({
        "alert_phrases": [
            {"text": "quiero ir a mi casa", "severity": 4, "regex": False},
            {"text": r"me duele el pecho", "severity": 5, "regex": True},
        ]
    })

    phrase = detector._rule_based_check("hoy quiero ir a mi casa")
    regex = detector._rule_based_check("me duele el pecho mucho")

    assert phrase is not None
    assert phrase.severity == 4
    assert regex is not None
    assert regex.severity == 5


def test_non_matching_rule_does_not_trigger_episode():
    detector = EpisodeDetector({
        "alert_phrases": [
            {"text": "quiero ir a mi casa", "severity": 4, "regex": False},
        ]
    })

    assert detector._rule_based_check("estoy sentado en casa") is None


@pytest.mark.asyncio
async def test_uncertain_patient_tag_triggers_deterministic_rules():
    detector = EpisodeDetector({})
    transcript = "[PACIENTE?] ayuda por favor"

    result = await detector.analyze(transcript, use_llm=False)

    assert _extract_patient_text(transcript) == ""
    assert _extract_rule_patient_text(transcript) == "ayuda por favor"
    assert result.is_episode is True
    assert result.severity == 5


@pytest.mark.asyncio
async def test_other_tag_still_does_not_trigger_deterministic_rules():
    detector = EpisodeDetector({})
    transcript = "[OTRO] ayuda por favor"

    result = await detector.analyze(transcript, use_llm=False)

    assert _extract_rule_patient_text(transcript) == ""
    assert result.is_episode is False
    assert result.severity == 0


def test_uncertain_patient_text_is_available_to_llm_prompt():
    transcript = "[PACIENTE?] ayuda\n[OTRO] tranquilo\n[PACIENTE] no se donde estoy"

    assert _extract_patient_text(transcript) == "no se donde estoy"
    assert _extract_possible_patient_text(transcript) == (
        "[PACIENTE?] ayuda\n[PACIENTE] no se donde estoy"
    )

    prompt = _build_analysis_prompt({}, transcript, short_term_memory="[12:00] [PACIENTE?] ayuda")

    assert "[PACIENTE?] significa" in prompt
    assert "[PACIENTE?] ayuda" in prompt
