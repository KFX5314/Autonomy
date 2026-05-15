from conftest import auth_headers
from src.routes import patients as patients_route


def _embedding(index: int) -> list[float]:
    vector = [0.0] * 192
    vector[index] = 1.0
    return vector


def _linked_patient_id(client, caregiver_token: str) -> int:
    response = client.get("/patients/", headers=auth_headers(caregiver_token))
    assert response.status_code == 200, response.text
    patients = response.json()
    assert len(patients) == 1
    return patients[0]["id"]


def test_upload_voice_sample_returns_active_metadata(
    client,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    register_patient(client, username="voice_route_patient")
    patient_id = _linked_patient_id(client, caregiver["access_token"])
    monkeypatch.setattr(patients_route, "create_embedding", lambda path: _embedding(0))

    response = client.post(
        f"/patients/{patient_id}/voice-sample",
        headers=auth_headers(caregiver["access_token"]),
        files={"file": ("sample.wav", b"fake audio", "audio/wav")},
    )

    assert response.status_code == 200, response.text
    samples = response.json()["samples"]
    assert samples[0]["active"] is True
    assert samples[0]["status"] == "active"
    assert samples[0]["consistency_similarity"] is None


def test_upload_inconsistent_voice_sample_returns_review_metadata(
    client,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    register_patient(client, username="voice_review_patient")
    patient_id = _linked_patient_id(client, caregiver["access_token"])
    embeddings = iter([_embedding(0), _embedding(1)])
    monkeypatch.setattr(patients_route, "create_embedding", lambda path: next(embeddings))

    for _ in range(2):
        response = client.post(
            f"/patients/{patient_id}/voice-sample",
            headers=auth_headers(caregiver["access_token"]),
            files={"file": ("sample.wav", b"fake audio", "audio/wav")},
        )
        assert response.status_code == 200, response.text

    samples = response.json()["samples"]
    assert [sample["status"] for sample in samples] == ["active", "review"]
    assert samples[1]["active"] is False
    assert samples[1]["consistency_similarity"] == 0.0
    assert samples[1]["reference_sample_id"] == samples[0]["id"]


def test_delete_voice_sample_recalculates_route_metadata(
    client,
    monkeypatch,
    register_caregiver,
    register_patient,
):
    caregiver = register_caregiver(client)
    register_patient(client, username="voice_delete_patient")
    patient_id = _linked_patient_id(client, caregiver["access_token"])
    embeddings = iter([_embedding(0), _embedding(1)])
    monkeypatch.setattr(patients_route, "create_embedding", lambda path: next(embeddings))

    for _ in range(2):
        response = client.post(
            f"/patients/{patient_id}/voice-sample",
            headers=auth_headers(caregiver["access_token"]),
            files={"file": ("sample.wav", b"fake audio", "audio/wav")},
        )
        assert response.status_code == 200, response.text

    first_sample_id = response.json()["samples"][0]["id"]
    response = client.delete(
        f"/patients/{patient_id}/voice-samples/{first_sample_id}",
        headers=auth_headers(caregiver["access_token"]),
    )

    assert response.status_code == 200, response.text
    samples = response.json()["samples"]
    assert len(samples) == 1
    assert samples[0]["active"] is True
    assert samples[0]["status"] == "active"
    assert samples[0]["consistency_similarity"] is None
