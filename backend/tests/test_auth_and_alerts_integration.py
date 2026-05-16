import re

import pytest

from conftest import auth_headers

pytestmark = pytest.mark.integration


def test_healthcheck(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "llm_available": True}


def test_public_patient_registration_is_rejected(client, register_caregiver):
    register_caregiver(client)

    response = client.post(
        "/auth/register",
        json={
            "role": "patient",
            "username": "public_patient",
            "password": "secret123",
            "full_name": "Paciente Publico",
            "caregiver_email": "care@example.com",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Patient accounts must be created by a caregiver"


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


def test_new_caregiver_can_list_empty_patients(client, register_caregiver):
    caregiver = register_caregiver(client, email="empty-care@example.com")

    response = client.get("/patients/", headers=auth_headers(caregiver["access_token"]))

    assert response.status_code == 200
    assert response.json() == []


def test_caregiver_can_create_patient_and_patient_can_login(client, register_caregiver):
    caregiver = register_caregiver(client, email="create-care@example.com")

    created = client.post(
        "/patients/",
        headers=auth_headers(caregiver["access_token"]),
        json={
            "full_name": "Paciente Nuevo",
            "username": "nuevo_paciente",
            "password": "secret123",
        },
    )

    assert created.status_code == 200, created.text
    created_json = created.json()
    assert created_json["full_name"] == "Paciente Nuevo"
    assert created_json["username"] == "nuevo_paciente"

    patients = client.get("/patients/", headers=auth_headers(caregiver["access_token"]))
    assert patients.status_code == 200
    assert [patient["username"] for patient in patients.json()] == ["nuevo_paciente"]

    patient_login = client.post(
        "/auth/login",
        json={"identifier": "nuevo_paciente", "password": "secret123", "role": "patient"},
    )
    assert patient_login.status_code == 200
    assert patient_login.json()["role"] == "patient"


def test_caregiver_can_create_patient_with_generated_username(client, register_caregiver):
    caregiver = register_caregiver(client, email="generated-care@example.com")

    created = client.post(
        "/patients/",
        headers=auth_headers(caregiver["access_token"]),
        json={
            "full_name": "Ana Lopez Garcia",
            "password": "secret123",
        },
    )

    assert created.status_code == 200, created.text
    username = created.json()["username"]
    assert username == "analop"

    patient_login = client.post(
        "/auth/login",
        json={"identifier": username, "password": "secret123", "role": "patient"},
    )
    assert patient_login.status_code == 200


def test_generated_patient_username_handles_duplicates_and_edge_names(
    client,
    register_caregiver,
):
    caregiver = register_caregiver(client, email="generated-edge-care@example.com")
    headers = auth_headers(caregiver["access_token"])

    first = client.post(
        "/patients/",
        headers=headers,
        json={"full_name": "Ana Lopez", "password": "secret123"},
    )
    second = client.post(
        "/patients/",
        headers=headers,
        json={"full_name": "Ana Lopez", "password": "secret123"},
    )
    single_name = client.post(
        "/patients/",
        headers=headers,
        json={"full_name": "Prince", "password": "secret123"},
    )
    random_fallback = client.post(
        "/patients/",
        headers=headers,
        json={"full_name": "!!!", "password": "secret123"},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert single_name.status_code == 200, single_name.text
    assert random_fallback.status_code == 200, random_fallback.text
    assert first.json()["username"] == "analop"
    assert second.json()["username"] == "analop1"
    assert single_name.json()["username"] == "prince"
    assert re.fullmatch(r"pac[a-z0-9]{6}", random_fallback.json()["username"])


def test_patient_cannot_create_patient(client, register_caregiver, register_patient):
    register_caregiver(client)
    patient = register_patient(client)

    response = client.post(
        "/patients/",
        headers=auth_headers(patient["access_token"]),
        json={
            "full_name": "Otro Paciente",
            "username": "otro_paciente",
            "password": "secret123",
        },
    )

    assert response.status_code == 403


def test_caregiver_create_patient_rejects_duplicate_username(
    client,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client, email="duplicate-care@example.com")
    register_patient(
        client,
        username="duplicado",
        caregiver_email="duplicate-care@example.com",
    )

    response = client.post(
        "/patients/",
        headers=auth_headers(caregiver["access_token"]),
        json={
            "full_name": "Paciente Duplicado",
            "username": "duplicado",
            "password": "secret123",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Username already registered"


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
