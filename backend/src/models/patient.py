from sqlalchemy import Column, BigInteger, TIMESTAMP, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from ..database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    # Stores {"samples": [...]} voice references used by speaker diarization.
    voice_embedding = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    user = relationship("User", back_populates="patient_profile")
    context = relationship("PatientContext", uselist=False, back_populates="patient", passive_deletes=True)
    transcripts = relationship("Transcript", back_populates="patient", passive_deletes=True)
    alerts = relationship("Alert", back_populates="patient", passive_deletes=True)
    journal_entries = relationship("JournalEntry", back_populates="patient", passive_deletes=True)


class PatientContext(Base):
    __tablename__ = "patient_context"

    patient_id = Column(BigInteger, ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    context_json = Column(JSON, nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    patient = relationship("Patient", back_populates="context")
