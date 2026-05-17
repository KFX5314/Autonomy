from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import auth_headers
from src.config import config
from src.models.journal import JournalEntry
from src.models.transcript import Transcript
from src.routes import audio as audio_route
from src.services import assistant_service

pytestmark = [pytest.mark.integration, pytest.mark.audio_mocked]


class CaptureLLM:
    def __init__(self, response: str = "Lo tenias apuntado en la memoria."):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def _linked_patient_id(client, caregiver_token: str) -> int:
    response = client.get("/patients/", headers=auth_headers(caregiver_token))
    assert response.status_code == 200, response.text
    patients = response.json()
    assert len(patients) == 1
    return patients[0]["id"]


def _set_wake_word_context(client, caregiver_token: str, patient_id: int) -> None:
    context = {
        "assistant_wake_words": ["asistente"],
        "episode_watch_instructions": "",
        "ui_color": "#4A90D9",
        "tts_enabled": True,
        "static_profile": {
            "preferred_name": "Paciente",
            "current_address": "Casa",
            "caregiver_names": ["Cuidador"],
            "medical_notes": [],
        },
        "assistant_style": {
            "tone": "calmado",
            "max_words": 40,
        },
        "alert_phrases": [],
    }
    response = client.put(
        f"/patients/{patient_id}/context",
        headers=auth_headers(caregiver_token),
        json={"context_json": context},
    )
    assert response.status_code == 200, response.text


def _seed_stm_and_journal(db_session, patient_id: int) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for idx in range(config.STM_MAX_UTTERANCES):
        started_at = now - timedelta(seconds=config.STM_MAX_UTTERANCES - idx)
        db_session.add(
            Transcript(
                patient_id=patient_id,
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=1),
                lang="es",
                transcript_text=f"[PACIENTE] memoria-stm-{idx}",
                stt_model="test",
            )
        )

    db_session.add(
        JournalEntry(
            patient_id=patient_id,
            covers_start=now - timedelta(hours=26),
            covers_end=now - timedelta(hours=25),
            created_at=now - timedelta(hours=25),
            summary_text="journal-fuera-24h",
        )
    )
    for idx in range(12):
        created_at = now - timedelta(minutes=12 - idx)
        db_session.add(
            JournalEntry(
                patient_id=patient_id,
                covers_start=created_at - timedelta(minutes=1),
                covers_end=created_at,
                created_at=created_at,
                summary_text=f"journal-dentro-24h-{idx}",
            )
        )
    db_session.commit()


def test_wake_word_audio_endpoint_uses_seeded_stm_and_full_retained_journal(
    client,
    db_session,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client, email="flow-care@example.com")
    patient = register_patient(
        client,
        username="flow_patient",
        caregiver_email="flow-care@example.com",
    )
    patient_id = _linked_patient_id(client, caregiver["access_token"])
    _set_wake_word_context(client, caregiver["access_token"], patient_id)
    _seed_stm_and_journal(db_session, patient_id)

    capture_llm = CaptureLLM()
    monkeypatch.setattr(assistant_service, "get_llm_provider", lambda: capture_llm)
    monkeypatch.setattr(audio_route, "should_schedule_journal", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        audio_route.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="1.0"),
    )
    monkeypatch.setattr(
        audio_route,
        "transcribe_audio",
        lambda path, audio_duration=None: {
            "text": "asistente que tenia que comprar?",
            "language": "es",
            "segments": [{"start": 0.0, "end": 1.0, "text": "asistente que tenia que comprar?"}],
        },
    )

    response = client.post(
        "/audio/chunk",
        headers=auth_headers(patient["access_token"]),
        files={"file": ("chunk.wav", b"fake audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "assistant"
    assert response.json()["reply_text"] == capture_llm.response
    assert len(capture_llm.calls) == 1
    prompt = capture_llm.calls[0][1]

    assert "memoria-stm-0" in prompt
    assert f"memoria-stm-{config.STM_MAX_UTTERANCES - 1}" in prompt
    assert "journal-fuera-24h" not in prompt
    for idx in range(12):
        assert f"journal-dentro-24h-{idx}" in prompt
