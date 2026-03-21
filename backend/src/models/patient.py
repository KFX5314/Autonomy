from sqlalchemy import Column, BigInteger, Date, Text, TIMESTAMP, ForeignKey, JSON, func
from sqlalchemy.orm import relationship
from ..database import Base


class Patient(Base):
    __tablename__ = "patients"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, unique=True)
    birth_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    voice_embedding = Column(JSON, nullable=True)  # 256-float list from Resemblyzer
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    user = relationship("User", back_populates="patient_profile")
    context = relationship("PatientContext", uselist=False, back_populates="patient")
    transcripts = relationship("Transcript", back_populates="patient")
    alerts = relationship("Alert", back_populates="patient")


class PatientContext(Base):
    __tablename__ = "patient_context"

    patient_id = Column(BigInteger, ForeignKey("patients.id"), primary_key=True)
    context_json = Column(JSON, nullable=False)
    updated_at = Column(TIMESTAMP, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    patient = relationship("Patient", back_populates="context")
