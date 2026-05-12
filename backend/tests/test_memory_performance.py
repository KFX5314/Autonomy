import time
from datetime import datetime, timedelta, timezone

import pytest

from src.config import config
from src.models.journal import JournalEntry
from src.models.patient import Patient
from src.models.user import User
from src.services import assistant_service, episode_detector

pytestmark = pytest.mark.performance


class FastLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def _mock_stm_at_limits() -> str:
    lines = [
        f"[12:{idx % 60:02d}] [PACIENTE] dato reciente {idx}"
        for idx in range(config.STM_MAX_UTTERANCES)
    ]
    base = "\n".join(lines)
    if len(base) > config.STM_MAX_CHARS:
        return base[: config.STM_MAX_CHARS]

    padding = config.STM_MAX_CHARS - len(base)
    idx = 0
    while padding > 0 and lines:
        add = min(padding, 16)
        lines[idx % len(lines)] += " " + ("x" * (add - 1))
        padding -= add
        idx += 1
    return "\n".join(lines)


def _text_at_limit(prefix: str, max_chars: int) -> str:
    if max_chars <= len(prefix):
        return prefix[:max_chars]
    return prefix + ("x" * (max_chars - len(prefix)))


def _make_patient(db_session) -> Patient:
    user = User(
        username="performance_patient",
        password_hash="hash",
        full_name="Paciente Performance",
        role="patient",
    )
    db_session.add(user)
    db_session.flush()
    patient = Patient(user_id=user.id)
    db_session.add(patient)
    db_session.flush()
    return patient


@pytest.mark.asyncio
async def test_full_stm_episode_analysis_overhead_is_under_one_second(monkeypatch):
    stm = _mock_stm_at_limits()
    fake = FastLLM('{"episode": false, "severity": 0, "reason": "normal", "reply": null}')
    monkeypatch.setattr(episode_detector, "get_llm_provider", lambda: fake)

    started = time.perf_counter()
    result = await episode_detector.EpisodeDetector({}).analyze(
        "[PACIENTE] Luego voy a comprar pan.",
        short_term_memory=stm,
    )
    elapsed = time.perf_counter() - started

    assert result.is_episode is False
    assert fake.calls
    assert stm in fake.calls[0][1]
    assert elapsed < 1.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_stm_and_full_24h_journal_assistant_overhead_is_under_one_second(
    db_session,
    monkeypatch,
):
    patient = _make_patient(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    entry_count = max(1, config.JOURNAL_MAX_ENTRIES)
    for idx in range(entry_count):
        created_at = now - timedelta(seconds=entry_count - idx)
        db_session.add(
            JournalEntry(
                patient_id=patient.id,
                covers_start=created_at - timedelta(minutes=5),
                covers_end=created_at,
                created_at=created_at,
                summary_text=_text_at_limit(f"journal-{idx}-", config.JOURNAL_ENTRY_MAX_CHARS),
            )
        )
    db_session.commit()

    stm = _mock_stm_at_limits()
    fake = FastLLM("Claro, te lo digo.")
    monkeypatch.setattr(assistant_service, "get_llm_provider", lambda: fake)

    started = time.perf_counter()
    result = await assistant_service.answer_patient_query(
        patient=patient,
        patient_text="que tenia que comprar?",
        stm=stm,
        db=db_session,
        full_transcript="[PACIENTE] asistente que tenia que comprar?",
    )
    elapsed = time.perf_counter() - started

    assert result["reply_text"] == "Claro, te lo digo."
    assert fake.calls
    prompt = fake.calls[0][1]
    assert stm in prompt
    assert "journal-0-" in prompt
    assert f"journal-{entry_count - 1}-" in prompt
    assert elapsed < 1.0
