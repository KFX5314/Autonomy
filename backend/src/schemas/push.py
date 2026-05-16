from datetime import datetime

from pydantic import BaseModel, Field


class PushTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=255)
    platform: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=128)


class PushTokenOut(BaseModel):
    id: int
    token: str
    platform: str | None = None
    device_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
