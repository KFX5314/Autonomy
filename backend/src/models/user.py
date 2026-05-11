from sqlalchemy import Column, BigInteger, String, Enum, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import relationship
from ..database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=True, unique=True)
    username = Column(String(64), nullable=True, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(Enum("caregiver", "patient", name="user_role"), nullable=False)
    caregiver_id = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.current_timestamp())

    caregiver = relationship("User", remote_side=[id], backref="patients_users")
    patient_profile = relationship("Patient", uselist=False, back_populates="user")
