from datetime import datetime

from pydantic import BaseModel


class JournalEntryOut(BaseModel):
    id: int
    patient_id: int
    covers_start: datetime
    covers_end: datetime
    summary_text: str
    created_at: datetime | None = None

    class Config:
        from_attributes = True
