from pydantic import BaseModel
from datetime import date, datetime


class PatientOut(BaseModel):
    id: int
    user_id: int
    full_name: str
    username: str | None = None
    birth_date: date | None = None
    notes: str | None = None
    created_at: datetime | None = None

    class Config:
        from_attributes = True


class PatientContextUpdate(BaseModel):
    context_json: dict


class PatientContextOut(BaseModel):
    patient_id: int
    context_json: dict
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ShortTermMemoryOut(BaseModel):
    patient_id: int
    window_minutes: int
    max_utterances: int
    generated_at: datetime
    memory: str
