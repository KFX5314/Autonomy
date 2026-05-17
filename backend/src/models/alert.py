from sqlalchemy import Column, BigInteger, SmallInteger, String, Text, Enum, TIMESTAMP, ForeignKey, func
from sqlalchemy.orm import relationship
from ..database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    transcript_id = Column(BigInteger, ForeignKey("transcripts.id", ondelete="SET NULL"), nullable=True)
    severity = Column(SmallInteger, nullable=False)
    reason = Column(String(512), nullable=False)
    llm_response = Column(Text, nullable=True)
    status = Column(Enum("NEW", "ACK", name="alert_status"), default="NEW")
    # Absolute path to the archived audio chunk that triggered this alert,
    # if any. Cleared after ACK + grace period or after the hard retention cap.
    audio_path = Column(String(512), nullable=True)
    acknowledged_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    patient = relationship("Patient", back_populates="alerts")
    transcript = relationship("Transcript", back_populates="alert")
