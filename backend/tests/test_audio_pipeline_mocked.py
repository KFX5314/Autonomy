from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from conftest import auth_headers
from src.models.alert import Alert
from src.models.patient import Patient
from src.models.transcript import Transcript
from src.models.user import User
from src.routes import audio as audio_route

pytestmark = [pytest.mark.integration, pytest.mark.audio_mocked]


class FakeLLM:
    async def generate(self, system: str, user: str) -> str:
        return "Estoy contigo. Voy a avisar a tu cuidador."


def _enroll_test_voice_sample(db_session, username: str) -> None:
    patient_user = db_session.query(User).filter(User.username == username).one()
    patient = db_session.query(Patient).filter(Patient.user_id == patient_user.id).one()
    patient.voice_embedding = {
        "samples": [
            {
                "id": "test-sample",
                "created_at": None,
                "embedding": [0.0] * 192,
            }
        ]
    }
    db_session.commit()


def test_audio_chunk_creates_alert_with_mocked_models(
    client,
    db_session,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    register_caregiver(client)
    patient = register_patient(client, username="audio_patient")
    _enroll_test_voice_sample(db_session, "audio_patient")

    alert_audio_dir = Path(".pytest_runtime") / "alert_audio" / uuid4().hex
    alert_audio_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(audio_route.config, "ALERTS_AUDIO_DIR", str(alert_audio_dir))
    monkeypatch.setattr(audio_route, "should_schedule_journal", lambda *args, **kwargs: False)
    monkeypatch.setattr(audio_route, "enforce_patient_audio_cap", lambda db, patient_id: None)
    monkeypatch.setattr(
        audio_route.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="1.2"),
    )
    monkeypatch.setattr(
        audio_route,
        "transcribe_audio",
        lambda path, audio_duration=None: {
            "text": "ayuda no se donde estoy",
            "language": "es",
            "segments": [{"start": 0.0, "end": 1.0, "text": "ayuda no se donde estoy"}],
        },
    )

    def fake_diarize(audio_path, segments, patient_embedding):
        segments[0].update({
            "speaker": "PACIENTE",
            "speaker_similarity": 0.55,
            "speaker_threshold": 0.40,
            "speaker_uncertain_threshold": 0.30,
            "speaker_confidence": "high",
        })
        return segments

    monkeypatch.setattr(audio_route, "diarize_segments", fake_diarize)
    monkeypatch.setattr(
        audio_route,
        "build_tagged_transcript",
        lambda segments: "[PACIENTE] ayuda no se donde estoy",
    )
    monkeypatch.setattr(
        "src.services.episode_detector.get_llm_provider",
        lambda: FakeLLM(),
    )

    response = client.post(
        "/audio/chunk",
        headers=auth_headers(patient["access_token"]),
        files={"file": ("chunk.wav", b"fake audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["episode"] is True
    assert body["severity"] == 5
    assert body["mode"] == "episode"
    assert body["alert_id"] is not None
    assert body["transcript"] == "[PACIENTE] ayuda no se donde estoy"
    assert body["reply_text"] == "Estoy contigo. Voy a avisar a tu cuidador."
    assert body["segments"][0]["speaker"] == "PACIENTE"

    assert db_session.query(Transcript).count() == 2
    alert = db_session.query(Alert).one()
    assert alert.reason == 'Palabra de emergencia detectada: "ayuda"'
    assert alert.audio_path is not None


def test_audio_chunk_rejects_invalid_mime(client, register_caregiver, register_patient):
    register_caregiver(client)
    patient = register_patient(client, username="mime_patient")

    response = client.post(
        "/audio/chunk",
        headers=auth_headers(patient["access_token"]),
        files={"file": ("not-audio.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415


def test_audio_chunk_with_only_other_speaker_skips_detector_and_llm(
    client,
    db_session,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    register_caregiver(client)
    patient = register_patient(client, username="other_only_patient")
    _enroll_test_voice_sample(db_session, "other_only_patient")

    monkeypatch.setattr(
        audio_route.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="10.0"),
    )
    monkeypatch.setattr(
        audio_route,
        "transcribe_audio",
        lambda path, audio_duration=None: {
            "text": "Conversación lejana de otra persona",
            "language": "es",
            "segments": [{"start": 0.0, "end": 9.0, "text": "Conversación lejana de otra persona"}],
        },
    )

    def fake_diarize(audio_path, segments, patient_embedding):
        segments[0].update({
            "speaker": "OTRO",
            "speaker_similarity": 0.03,
            "speaker_threshold": 0.40,
            "speaker_uncertain_threshold": 0.30,
            "speaker_confidence": "high",
        })
        return segments

    class FailingDetector:
        def __init__(self, *args, **kwargs):
            raise AssertionError("EpisodeDetector should not run for OTRO-only audio")

    monkeypatch.setattr(audio_route, "diarize_segments", fake_diarize)
    monkeypatch.setattr(
        audio_route,
        "build_tagged_transcript",
        lambda segments: "[OTRO] Conversación lejana de otra persona",
    )
    monkeypatch.setattr(audio_route, "EpisodeDetector", FailingDetector)

    response = client.post(
        "/audio/chunk",
        headers=auth_headers(patient["access_token"]),
        files={"file": ("chunk.wav", b"fake audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["episode"] is False
    assert body["severity"] == 0
    assert body["mode"] == "idle"
    assert body["reason"] == "Sin voz del paciente"
    assert body["transcript"] == "[OTRO] Conversación lejana de otra persona"
    assert body["segments"][0]["speaker"] == "OTRO"

    assert db_session.query(Transcript).count() == 1
    assert db_session.query(Alert).count() == 0
