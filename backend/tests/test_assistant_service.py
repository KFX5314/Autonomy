from datetime import datetime, timedelta, timezone

import pytest

from src.models.journal import JournalEntry
from src.models.patient import Patient
from src.models.user import User
from src.services import assistant_service

pytestmark = pytest.mark.integration


class CaptureLLM:
    def __init__(self, response: str = "Vale, te ayudo."):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def _make_patient(db_session) -> Patient:
    caregiver = User(
        email="assistant-care@example.com",
        password_hash="hash",
        full_name="Cuidador Asistente",
        role="caregiver",
    )
    db_session.add(caregiver)
    db_session.flush()
    user = User(
        username="assistant_patient",
        password_hash="hash",
        full_name="Paciente Asistente",
        role="patient",
        caregiver_id=caregiver.id,
    )
    db_session.add(user)
    db_session.flush()
    patient = Patient(user_id=user.id)
    db_session.add(patient)
    db_session.flush()
    return patient


def test_wake_word_assistant_prompt_uses_final_response_guardrails():
    system_prompt = assistant_service._build_system_prompt({})

    assert "avisaras al cuidador" not in system_prompt
    assert "responsables ya estan configurados" in system_prompt
    assert "tienes alergia a" in system_prompt
    assert "nunca digas 'estas alergico'" in system_prompt


@pytest.mark.asyncio
async def test_wake_word_assistant_uses_all_last_24h_journal_entries(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    db_session.add(
        JournalEntry(
            patient_id=patient.id,
            covers_start=now - timedelta(hours=26),
            covers_end=now - timedelta(hours=25),
            created_at=now - timedelta(hours=25),
            summary_text="old-outside-window",
        )
    )
    for idx in range(12):
        created_at = now - timedelta(minutes=60 - idx)
        db_session.add(
            JournalEntry(
                patient_id=patient.id,
                covers_start=created_at - timedelta(minutes=5),
                covers_end=created_at,
                created_at=created_at,
                summary_text=f"inside-window-{idx}",
            )
        )
    db_session.commit()

    fake = CaptureLLM()
    monkeypatch.setattr(assistant_service, "get_llm_provider", lambda: fake)

    result = await assistant_service.answer_patient_query(
        patient=patient,
        patient_text="que tenia que comprar?",
        stm="[12:00] [PACIENTE] iba a comprar pan",
        db=db_session,
        full_transcript="[PACIENTE] asistente que tenia que comprar?",
    )

    assert result["reply_text"] == "Vale, te ayudo."
    assert len(fake.calls) == 1
    prompt = fake.calls[0][1]
    assert "old-outside-window" not in prompt
    for idx in range(12):
        assert f"inside-window-{idx}" in prompt
    positions = [prompt.index(f"inside-window-{idx}") for idx in range(12)]
    assert positions == sorted(positions)
