from sqlalchemy import Column, BigInteger, DateTime, String, TIMESTAMP, ForeignKey, Index, func
from sqlalchemy.orm import relationship
from ..database import Base


class JournalEntry(Base):
    """
    Long-term memory entries: 1-2 short sentences condensed by the LLM from a
    window of recent patient transcripts. Written by a background task after
    the audio-chunk response is returned (zero request-path latency).
    """

    __tablename__ = "journal_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    covers_start = Column(DateTime, nullable=False)
    covers_end = Column(DateTime, nullable=False)
    summary_text = Column(String(500), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    patient = relationship("Patient", back_populates="journal_entries")

    __table_args__ = (
        Index("ix_journal_patient_created", "patient_id", "created_at"),
    )
