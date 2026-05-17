from datetime import datetime, timedelta, timezone

import pytest

from src.models.journal import JournalEntry
from src.models.patient import Patient
from src.models.transcript import Transcript
from src.models.user import User
from src.services import memory_service

pytestmark = pytest.mark.integration


class FakeLLM:
    def __init__(self, response: str = "Resumen de prueba."):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def _make_patient(db_session, username: str = "memory_patient") -> Patient:
    caregiver = User(
        email=f"{username}-care@example.com",
        password_hash="hash",
        full_name="Cuidador Memoria",
        role="caregiver",
    )
    db_session.add(caregiver)
    db_session.flush()
    user = User(
        username=username,
        password_hash="hash",
        full_name="Paciente Memoria",
        role="patient",
        caregiver_id=caregiver.id,
    )
    db_session.add(user)
    db_session.flush()
    patient = Patient(user_id=user.id)
    db_session.add(patient)
    db_session.flush()
    return patient


def _add_transcript(db_session, patient_id: int, started_at: datetime, text: str) -> Transcript:
    transcript = Transcript(
        patient_id=patient_id,
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=5),
        lang="es",
        transcript_text=text,
        stt_model="test",
    )
    db_session.add(transcript)
    db_session.flush()
    return transcript


@pytest.fixture(autouse=True)
def clear_journal_in_flight():
    with memory_service._journal_in_flight_lock:
        memory_service._journal_in_flight.clear()
    yield
    with memory_service._journal_in_flight_lock:
        memory_service._journal_in_flight.clear()


@pytest.mark.asyncio
async def test_silence_only_stm_skips_journal_without_llm(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    for i in range(12):
        _add_transcript(
            db_session,
            patient.id,
            now.replace(tzinfo=None) - timedelta(seconds=i * 25),
            "   ",
        )
    db_session.commit()

    fake = FakeLLM()
    monkeypatch.setattr(memory_service, "get_llm_provider", lambda: fake)

    await memory_service.summarize_and_append(patient.id, db=db_session, now=now)

    assert fake.calls == []
    assert db_session.query(JournalEntry).filter(JournalEntry.patient_id == patient.id).count() == 0


@pytest.mark.asyncio
async def test_other_only_stm_skips_journal_without_llm(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    _add_transcript(
        db_session,
        patient.id,
        now.replace(tzinfo=None) - timedelta(seconds=10),
        "[OTRO] Chao, buenas noches.",
    )
    db_session.commit()

    fake = FakeLLM("No deberia llamarse.")
    monkeypatch.setattr(memory_service, "get_llm_provider", lambda: fake)

    assert memory_service.should_schedule_journal(patient.id, db=db_session, now=now) is False
    await memory_service.summarize_and_append(patient.id, db=db_session, now=now)

    assert fake.calls == []
    assert db_session.query(JournalEntry).filter(JournalEntry.patient_id == patient.id).count() == 0


@pytest.mark.asyncio
async def test_sparse_new_stm_still_creates_journal_entry(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    _add_transcript(
        db_session,
        patient.id,
        now.replace(tzinfo=None) - timedelta(minutes=1),
        "[PACIENTE] He comido sopa.",
    )
    db_session.commit()

    fake = FakeLLM("El paciente dijo que habia comido sopa.")
    monkeypatch.setattr(memory_service, "get_llm_provider", lambda: fake)

    await memory_service.summarize_and_append(patient.id, db=db_session, now=now)

    entry = db_session.query(JournalEntry).filter(JournalEntry.patient_id == patient.id).one()
    assert "sopa" in entry.summary_text
    assert len(fake.calls) == 1


def test_short_term_paginates_past_empty_recent_transcripts(db_session):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    base = now.replace(tzinfo=None)
    for idx in range(8):
        _add_transcript(db_session, patient.id, base - timedelta(seconds=idx), "   ")
    _add_transcript(db_session, patient.id, base - timedelta(seconds=20), "[PACIENTE] linea util antigua")
    _add_transcript(db_session, patient.id, base - timedelta(seconds=10), "[PACIENTE] linea util nueva")
    db_session.commit()

    stm = memory_service.get_short_term(
        patient.id,
        db_session,
        now=now,
        max_utterances=2,
        max_chars=1000,
    )

    assert "linea util antigua" in stm
    assert "linea util nueva" in stm
    assert stm.index("linea util antigua") < stm.index("linea util nueva")


def test_short_term_preserves_fragment_order_inside_transcript(db_session):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc)
    _add_transcript(
        db_session,
        patient.id,
        now.replace(tzinfo=None) - timedelta(seconds=10),
        "[PACIENTE] Hola asistente. [ASISTENTE] Hola, estoy contigo.",
    )
    db_session.commit()

    lines = memory_service.get_short_term(
        patient.id,
        db_session,
        now=now,
        max_utterances=2,
    ).splitlines()

    assert lines[0].endswith("[PACIENTE] Hola asistente.")
    assert lines[1].endswith("[ASISTENTE] Hola, estoy contigo.")


@pytest.mark.asyncio
async def test_journal_summary_can_include_assistant_and_other_lines(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 7, tzinfo=timezone.utc)
    base = now.replace(tzinfo=None)
    _add_transcript(db_session, patient.id, base - timedelta(minutes=3), "[ASISTENTE] Esta todo bien?")
    _add_transcript(db_session, patient.id, base - timedelta(minutes=2), "[OTRO] Si, esta conmigo.")
    _add_transcript(db_session, patient.id, base - timedelta(minutes=1), "[ASISTENTE] Me quedo pendiente.")
    db_session.commit()

    fake = FakeLLM("El asistente pregunto si todo iba bien y otra persona confirmo que estaba acompanado.")
    monkeypatch.setattr(memory_service, "get_llm_provider", lambda: fake)

    await memory_service.summarize_and_append(patient.id, db=db_session, now=now)

    entry = db_session.query(JournalEntry).filter(JournalEntry.patient_id == patient.id).one()
    assert "acompanado" in entry.summary_text
    assert len(fake.calls) == 1
    assert "[ASISTENTE]" in fake.calls[0][1]
    assert "[OTRO]" in fake.calls[0][1]


def test_journal_schedule_waits_until_selected_stm_turns_over(db_session):
    now = datetime(2026, 5, 12, 12, 7, tzinfo=timezone.utc)
    latest_end = datetime(2026, 5, 12, 12, 3)

    overlapping = _make_patient(db_session, "overlapping_patient")
    db_session.add(
        JournalEntry(
            patient_id=overlapping.id,
            covers_start=datetime(2026, 5, 12, 11, 58),
            covers_end=latest_end,
            summary_text="Resumen anterior.",
        )
    )
    for minute in (2, 4, 5):
        _add_transcript(db_session, overlapping.id, datetime(2026, 5, 12, 12, minute), "[PACIENTE] linea nueva")

    turned_over = _make_patient(db_session, "turned_over_patient")
    db_session.add(
        JournalEntry(
            patient_id=turned_over.id,
            covers_start=datetime(2026, 5, 12, 11, 58),
            covers_end=latest_end,
            summary_text="Resumen anterior.",
        )
    )
    for minute in (4, 5, 6):
        _add_transcript(db_session, turned_over.id, datetime(2026, 5, 12, 12, minute), "[PACIENTE] linea nueva")
    db_session.commit()

    assert memory_service.should_schedule_journal(overlapping.id, db=db_session, now=now) is False
    assert memory_service.should_schedule_journal(turned_over.id, db=db_session, now=now) is True


@pytest.mark.asyncio
async def test_journal_coverage_matches_selected_stm_timestamps(db_session, monkeypatch):
    patient = _make_patient(db_session)
    now = datetime(2026, 5, 12, 12, 20, tzinfo=timezone.utc)
    selected_times = [
        datetime(2026, 5, 12, 12, 16),
        datetime(2026, 5, 12, 12, 17),
        datetime(2026, 5, 12, 12, 18),
    ]
    for idx, started_at in enumerate(selected_times):
        _add_transcript(db_session, patient.id, started_at, f"[PACIENTE] actividad {idx}")
    db_session.commit()

    fake = FakeLLM("El paciente describio varias actividades recientes.")
    monkeypatch.setattr(memory_service, "get_llm_provider", lambda: fake)

    await memory_service.summarize_and_append(patient.id, db=db_session, now=now)

    entry = db_session.query(JournalEntry).filter(JournalEntry.patient_id == patient.id).one()
    assert entry.covers_start == selected_times[0]
    assert entry.covers_end == selected_times[-1]
