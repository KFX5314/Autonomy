"""
Authentication routes: register and login.
"""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..models.patient import Patient, PatientContext
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from ..auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,64}$")


def _normalize_email(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _normalize_username(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _validate_username(username: str | None) -> str:
    if not username:
        raise HTTPException(status_code=400, detail="Patient must specify username")
    if not _USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-64 chars and use only letters, numbers, dots, hyphens or underscores",
        )
    return username


def _token_response(user: User) -> TokenResponse:
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
    )


@router.post("/register", response_model=TokenResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if req.role not in ("caregiver", "patient"):
        raise HTTPException(status_code=400, detail="Role must be 'caregiver' or 'patient'")

    email = _normalize_email(req.email)
    username = _normalize_username(req.username)
    caregiver_email = _normalize_email(req.caregiver_email)

    if not req.password:
        raise HTTPException(status_code=400, detail="Password is required")
    if not req.full_name.strip():
        raise HTTPException(status_code=400, detail="Full name is required")

    if req.role == "caregiver":
        if not email:
            raise HTTPException(status_code=400, detail="Caregiver must specify email")
        username = None
    else:
        username = _validate_username(username)
        email = email or None

    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if username and db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    caregiver_id = None
    if req.role == "patient":
        if not caregiver_email:
            raise HTTPException(status_code=400, detail="Patient must specify caregiver_email")
        caregiver = db.query(User).filter(
            User.email == caregiver_email, User.role == "caregiver"
        ).first()
        if not caregiver:
            raise HTTPException(status_code=404, detail="Caregiver not found")
        caregiver_id = caregiver.id

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        role=req.role,
        caregiver_id=caregiver_id,
    )
    db.add(user)
    db.flush()

    if req.role == "patient":
        patient = Patient(user_id=user.id)
        db.add(patient)
        db.flush()
        default_context = {
            "episode_watch_instructions": "",
            "ui_color": "#4A90D9",
            "tts_enabled": True,
            "static_profile": {
                "preferred_name": req.full_name.strip().split()[0],
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

    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    identifier = (req.identifier or "").strip().lower()
    if not identifier:
        raise HTTPException(status_code=400, detail="Identifier is required")
    if req.role not in ("caregiver", "patient"):
        raise HTTPException(status_code=400, detail="Role must be 'caregiver' or 'patient'")

    if req.role == "caregiver":
        user = db.query(User).filter(
            User.email == identifier, User.role == "caregiver"
        ).first()
    else:
        user = db.query(User).filter(
            User.username == identifier, User.role == "patient"
        ).first()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return user
