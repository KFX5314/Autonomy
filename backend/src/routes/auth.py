"""
Authentication routes: register and login.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from ..auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    # Check if email already exists
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    if req.role not in ("caregiver", "patient"):
        raise HTTPException(status_code=400, detail="Role must be 'caregiver' or 'patient'")

    caregiver_id = None
    if req.role == "patient":
        if not req.caregiver_email:
            raise HTTPException(status_code=400, detail="Patient must specify caregiver_email")
        caregiver = db.query(User).filter(
            User.email == req.caregiver_email, User.role == "caregiver"
        ).first()
        if not caregiver:
            raise HTTPException(status_code=404, detail="Caregiver not found")
        caregiver_id = caregiver.id

    user = User(
        email=req.email,
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        role=req.role,
        caregiver_id=caregiver_id,
    )
    db.add(user)
    db.flush()

    # If patient, create patient profile with default context
    if req.role == "patient":
        patient = Patient(user_id=user.id)
        db.add(patient)
        db.flush()
        default_context = {
            "static_profile": {
                "preferred_name": req.full_name.split()[0],
                "current_address": "",
                "caregiver_names": [],
                "medical_notes": [],
            },
            "risk_rules": [],
            "trigger_phrases": [
                {"text": "ayuda", "severity": 5},
                {"text": "no sé dónde estoy", "severity": 5},
            ],
            "assistant_style": {
                "language": "es-ES",
                "tone": "calmado",
                "max_words": 40,
            },
        }
        ctx = PatientContext(patient_id=patient.id, context_json=default_context)
        db.add(ctx)

    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
    )


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user
