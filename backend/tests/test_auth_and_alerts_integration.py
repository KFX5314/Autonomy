import pytest

from conftest import auth_headers

pytestmark = pytest.mark.integration


def test_healthcheck(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm_available": True}


def test_caregiver_and_patient_register_login_me_and_settings(
    client,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    patient = register_patient(client)

    assert caregiver["email"] == "care@example.com"
    assert caregiver["username"] is None
    assert patient["email"] is None
    assert patient["username"] == "paciente_test"

    caregiver_login = client.post(
        "/auth/login",
        json={"identifier": "care@example.com", "password": "secret123", "role": "caregiver"},
    )
    patient_login = client.post(
        "/auth/login",
        json={"identifier": "paciente_test", "password": "secret123", "role": "patient"},
    )

    assert caregiver_login.status_code == 200
    assert patient_login.status_code == 200

    patient_me = client.get("/auth/me", headers=auth_headers(patient_login.json()["access_token"]))
    assert patient_me.status_code == 200
    assert patient_me.json()["email"] is None
    assert patient_me.json()["username"] == "paciente_test"

    settings = client.get(
        "/patients/me/settings",
        headers=auth_headers(patient_login.json()["access_token"]),
    )
    assert settings.status_code == 200
    assert settings.json()["tts_enabled"] is True
    assert settings.json()["ui_color"] == "#4A90D9"


def test_caregiver_lists_only_linked_patients(client, register_caregiver, register_patient):
    caregiver_1 = register_caregiver(client, email="care1@example.com")
    register_patient(client, username="patient_1", caregiver_email="care1@example.com")

    register_caregiver(client, email="care2@example.com")
    register_patient(client, username="patient_2", caregiver_email="care2@example.com")

    response = client.get("/patients/", headers=auth_headers(caregiver_1["access_token"]))

    assert response.status_code == 200
    patients = response.json()
    assert len(patients) == 1
    assert patients[0]["username"] == "patient_1"


def test_patient_cannot_access_caregiver_routes(client, register_caregiver, register_patient):
    register_caregiver(client)
    patient = register_patient(client)

    response = client.get("/patients/", headers=auth_headers(patient["access_token"]))

    assert response.status_code == 403


def test_patient_logout_warning_creates_alert_and_ack_respects_ownership(
    client,
    register_caregiver,
    register_patient,
):
    owner = register_caregiver(client, email="owner@example.com")
    patient = register_patient(client, username="patient_owner", caregiver_email="owner@example.com")
    other = register_caregiver(client, email="other@example.com")

    warning = client.post(
        "/patients/me/logout-warning",
        headers=auth_headers(patient["access_token"]),
    )
    assert warning.status_code == 200
    alert_id = warning.json()["alert_id"]

    forbidden_ack = client.post(
        f"/alerts/{alert_id}/ack",
        headers=auth_headers(other["access_token"]),
        json={"status": "ACK"},
    )
    assert forbidden_ack.status_code == 403

    alerts = client.get("/alerts/", headers=auth_headers(owner["access_token"]))
    assert alerts.status_code == 200
    assert len(alerts.json()) == 1
    assert alerts.json()[0]["reason"] == "El paciente ha cerrado sesión en la app"

    ack = client.post(
        f"/alerts/{alert_id}/ack",
        headers=auth_headers(owner["access_token"]),
        json={"status": "ACK"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACK"
