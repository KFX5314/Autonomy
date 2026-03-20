from pydantic import BaseModel
from datetime import datetime


class AlertOut(BaseModel):
    id: int
    patient_id: int
    severity: int
    reason: str
    llm_response: str | None = None
    status: str
    created_at: datetime | None = None

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
