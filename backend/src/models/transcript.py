from sqlalchemy import Column, BigInteger, DateTime, String, Text, TIMESTAMP, ForeignKey, Index, func
from sqlalchemy.orm import relationship
from ..database import Base


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id"), nullable=False)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=False)
    lang = Column(String(8), default="es")
    transcript_text = Column(Text, nullable=False)
    stt_model = Column(String(64), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    patient = relationship("Patient", back_populates="transcripts")
    alert = relationship("Alert", uselist=False, back_populates="transcript")

    __table_args__ = (
        # Short-term memory queries filter by patient + recent started_at
        Index("ix_transcript_patient_started", "patient_id", "started_at"),
    )
