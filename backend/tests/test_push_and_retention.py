from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from conftest import auth_headers
from src.models.alert import Alert
from src.models.journal import JournalEntry
from src.models.patient import Patient
from src.models.push_token import PushToken
from src.models.transcript import Transcript
from src.models.user import User
from src.services import expo_push_service


def _linked_patient(client, db_session, caregiver_token: str) -> Patient:
    response = client.get("/patients/", headers=auth_headers(caregiver_token))
    assert response.status_code == 200, response.text
    patient_id = response.json()[0]["id"]
    return db_session.query(Patient).filter(Patient.id == patient_id).one()


def test_caregiver_can_register_push_token_and_patient_cannot(
    client,
    db_session,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    patient = register_patient(client, username="push_patient")

    response = client.post(
        "/push-tokens/",
        headers=auth_headers(caregiver["access_token"]),
        json={
            "token": "ExponentPushToken[test-token]",
            "platform": "android",
            "device_id": "caregiver-device",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"] == "ExponentPushToken[test-token]"
    assert body["platform"] == "android"
    row = db_session.query(PushToken).one()
    assert row.user_id == caregiver["user_id"]

    forbidden = client.post(
        "/push-tokens/",
        headers=auth_headers(patient["access_token"]),
        json={"token": "ExponentPushToken[patient-token]"},
    )
    assert forbidden.status_code == 403


def test_expo_push_failure_does_not_raise(db_session, monkeypatch):
    caregiver = User(
        email="pushfail@example.com",
        password_hash="hash",
        full_name="Caregiver",
        role="caregiver",
    )
    db_session.add(caregiver)
    db_session.flush()
    db_session.add(PushToken(user_id=caregiver.id, token="ExponentPushToken[fail]"))
    db_session.commit()

    def fail_post(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(expo_push_service.httpx, "post", fail_post)

    attempted = expo_push_service.notify_caregiver_alert(
        caregiver_id=caregiver.id,
        alert_id=123,
        patient_name="Paciente",
        severity=5,
        reason="ayuda",
        db=db_session,
    )

    assert attempted == 0
    assert db_session.query(PushToken).count() == 1


def test_expo_push_removes_device_not_registered_tokens(db_session, monkeypatch):
    caregiver = User(
        email="pushclean@example.com",
        password_hash="hash",
        full_name="Caregiver",
        role="caregiver",
    )
    db_session.add(caregiver)
    db_session.flush()
    db_session.add(PushToken(user_id=caregiver.id, token="ExponentPushToken[stale]"))
    db_session.commit()

    def fake_post(*args, **kwargs):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "data": [
                    {
                        "status": "error",
                        "details": {"error": "DeviceNotRegistered"},
                    }
                ]
            },
        )

    monkeypatch.setattr(expo_push_service.httpx, "post", fake_post)

    attempted = expo_push_service.notify_caregiver_alert(
        caregiver_id=caregiver.id,
        alert_id=124,
        patient_name="Paciente",
        severity=4,
        reason="alerta",
        db=db_session,
    )

    assert attempted == 1
    assert db_session.query(PushToken).count() == 0


def test_caregiver_gets_apply_opportunistic_retention_cleanup(
    client,
    db_session,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    register_patient(client, username="cleanup_patient")
    patient = _linked_patient(client, db_session, caregiver["access_token"])

    now = datetime.now()
    db_session.add(
        JournalEntry(
            patient_id=patient.id,
            covers_start=now - timedelta(hours=30),
            covers_end=now - timedelta(hours=29),
            summary_text="old journal",
            created_at=now - timedelta(hours=30),
        )
    )
    db_session.add(
        JournalEntry(
            patient_id=patient.id,
            covers_start=now - timedelta(hours=1),
            covers_end=now - timedelta(minutes=30),
            summary_text="new journal",
            created_at=now - timedelta(minutes=30),
        )
    )
    db_session.add(
        Transcript(
            patient_id=patient.id,
            started_at=now - timedelta(days=20),
            ended_at=now - timedelta(days=20),
            lang="es",
            transcript_text="[PACIENTE] old",
            stt_model="test",
            created_at=now - timedelta(days=20),
        )
    )
    db_session.add(
        Transcript(
            patient_id=patient.id,
            started_at=now - timedelta(minutes=5),
            ended_at=now - timedelta(minutes=4),
            lang="es",
            transcript_text="[PACIENTE] new",
            stt_model="test",
            created_at=now - timedelta(minutes=5),
        )
    )

    audio_dir = Path(".pytest_runtime") / "retention" / uuid4().hex
    audio_dir.mkdir(parents=True, exist_ok=True)
    old_audio = audio_dir / "old-alert.m4a"
    old_audio.write_bytes(b"audio")
    db_session.add(
        Alert(
            patient_id=patient.id,
            severity=3,
            reason="old alert audio",
            audio_path=str(old_audio),
            created_at=now - timedelta(days=40),
        )
    )
    db_session.commit()

    journal = client.get(
        f"/patients/{patient.id}/journal",
        headers=auth_headers(caregiver["access_token"]),
    )
    assert journal.status_code == 200, journal.text
    assert [entry["summary_text"] for entry in journal.json()] == ["new journal"]

    stm = client.get(
        f"/patients/{patient.id}/short-term-memory",
        headers=auth_headers(caregiver["access_token"]),
    )
    assert stm.status_code == 200, stm.text

    alerts = client.get("/alerts/", headers=auth_headers(caregiver["access_token"]))
    assert alerts.status_code == 200, alerts.text

    db_session.rollback()
    db_session.expire_all()
    assert db_session.query(JournalEntry).count() == 1
    assert db_session.query(Transcript).count() == 1
    assert db_session.query(Alert).one().audio_path is None
    assert not old_audio.exists()
