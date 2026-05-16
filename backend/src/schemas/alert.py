from pydantic import BaseModel
from datetime import datetime


class AlertOut(BaseModel):
    id: int
    patient_id: int
    severity: int
    reason: str
    llm_response: str | None = None
    status: str
    transcript_text: str | None = None
    audio_url: str | None = None
    created_at: datetime | None = None
    acknowledged_at: datetime | None = None

    class Config:
        from_attributes = True


class AlertAck(BaseModel):
    status: str = "ACK"


class AudioChunkResponse(BaseModel):
    transcript: str
    episode: bool
    severity: int = 0
    reason: str = ""
    reply_text: str | None = None
    alert_id: int | None = None
    # "idle" (no action, including stored [ASISTENTE] echo), "episode" (alert
    # fired), "assistant" (wake-word QA).
    mode: str = "idle"
    segments: list[dict] = []    # [{"start": float, "end": float}] for VAD calibration
