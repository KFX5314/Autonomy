from __future__ import annotations

import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from conftest import auth_headers
from src.config import DEV_DB_PASSWORD, config
from src.models.journal import JournalEntry
from src.models.transcript import Transcript

pytestmark = [pytest.mark.integration, pytest.mark.server_e2e]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_URL = os.getenv("TFG_BACKEND_E2E_URL", "http://127.0.0.1:8000")


def _powershell_command() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _wait_for_health(url: str, timeout_s: int = 60) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{url}/health", timeout=2.0)
            if response.status_code == 200:
                return
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"Backend did not become healthy at {url}: {last_error}")


def _stop_port_8000(ps: str) -> None:
    subprocess.run(
        [
            ps,
            "-NoProfile",
            "-Command",
            (
                "$pids = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | "
                "Select-Object -ExpandProperty OwningProcess -Unique; "
                "foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }"
            ),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.fixture
def external_backend():
    if os.getenv("TFG_RUN_SERVER_E2E") != "1":
        pytest.skip("Set TFG_RUN_SERVER_E2E=1 to run the external server memory flow test.")

    if os.getenv("TFG_SERVER_E2E_USE_EXISTING") == "1":
        _wait_for_health(BACKEND_URL, timeout_s=10)
        yield BACKEND_URL
        return

    ps = _powershell_command()
    if not ps:
        pytest.skip("PowerShell is required to start scripts/run-backend-e2e.ps1.")

    env = os.environ.copy()
    env.update(
        {
            "DB_HOST": os.getenv("TEST_DB_HOST", "127.0.0.1"),
            "DB_PORT": os.getenv("TEST_DB_PORT", "3306"),
            "DB_NAME": os.getenv("TEST_DB_NAME", "tfg_demencia_test"),
            "DB_USER": os.getenv("TEST_DB_USER", "tfg_app"),
            "DB_PASSWORD": os.getenv("TEST_DB_PASSWORD", DEV_DB_PASSWORD),
        }
    )
    process = subprocess.Popen(
        [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "run-backend-e2e.ps1"),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_health(BACKEND_URL)
        yield BACKEND_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        _stop_port_8000(ps)


def _seed_memory_rows(db_session, patient_id: int) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for idx in range(config.STM_MAX_UTTERANCES):
        started_at = now - timedelta(seconds=config.STM_MAX_UTTERANCES - idx)
        db_session.add(
            Transcript(
                patient_id=patient_id,
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=1),
                lang="es",
                transcript_text=f"[PACIENTE] server-stm-{idx}",
                stt_model="server-e2e",
            )
        )

    db_session.add(
        JournalEntry(
            patient_id=patient_id,
            covers_start=now - timedelta(hours=26),
            covers_end=now - timedelta(hours=25),
            created_at=now - timedelta(hours=25),
            summary_text="server-journal-fuera-24h",
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
                summary_text=f"server-journal-dentro-24h-{idx}",
            )
        )
    db_session.commit()


def test_external_server_memory_endpoints_use_seeded_stm_and_journal(external_backend, db_session):
    with httpx.Client(base_url=external_backend, timeout=10.0) as client:
        caregiver_email = "server-flow-care@example.com"
        caregiver = client.post(
            "/auth/register",
            json={
                "role": "caregiver",
                "email": caregiver_email,
                "password": "secret123",
                "full_name": "Cuidador Server",
            },
        )
        assert caregiver.status_code == 200, caregiver.text
        caregiver_token = caregiver.json()["access_token"]
        patient = client.post(
            "/patients/",
            headers=auth_headers(caregiver_token),
            json={
                "username": "server_flow_patient",
                "password": "secret123",
                "full_name": "Paciente Server",
            },
        )
        assert patient.status_code == 200, patient.text

        patients = client.get("/patients/", headers=auth_headers(caregiver_token))
        assert patients.status_code == 200, patients.text
        patient_id = patients.json()[0]["id"]

        _seed_memory_rows(db_session, patient_id)

        stm = client.get(
            f"/patients/{patient_id}/short-term-memory",
            headers=auth_headers(caregiver_token),
        )
        assert stm.status_code == 200, stm.text
        memory_text = stm.json()["memory"]
        assert "server-stm-0" in memory_text
        assert f"server-stm-{config.STM_MAX_UTTERANCES - 1}" in memory_text

        journal = client.get(
            f"/patients/{patient_id}/journal?since_hours=24&limit=100",
            headers=auth_headers(caregiver_token),
        )
        assert journal.status_code == 200, journal.text
        summaries = [entry["summary_text"] for entry in journal.json()]
        assert "server-journal-fuera-24h" not in summaries
        for idx in range(12):
            assert f"server-journal-dentro-24h-{idx}" in summaries
