"""
Helpers for creating patient accounts and their default profile context.
"""

import re
import secrets
import string
import unicodedata

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..auth import hash_password
from ..models.patient import Patient, PatientContext
from ..models.user import User

_USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,64}$")
_RANDOM_USERNAME_CHARS = string.ascii_lowercase + string.digits


def normalize_email(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def normalize_username(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def validate_patient_username(username: str | None) -> str:
    if not username:
        raise HTTPException(status_code=400, detail="Patient must specify username")
    if not _USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=400,
            detail="Username must be 3-64 chars and use only letters, numbers, dots, hyphens or underscores",
        )
    return username


def _username_tokens(full_name: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(full_name or ""))
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    clean = re.sub(r"[^a-z0-9]+", " ", without_accents.lower())
    return [token for token in clean.split() if token]


def _random_username_base() -> str:
    return "pac" + "".join(secrets.choice(_RANDOM_USERNAME_CHARS) for _ in range(6))


def _username_base_from_name(full_name: str) -> str:
    try:
        tokens = _username_tokens(full_name)
        if len(tokens) >= 2:
            base = tokens[0][:3] + tokens[1][:3]
        elif len(tokens) == 1:
            base = tokens[0][:6]
        else:
            base = _random_username_base()
        if len(base) < 3:
            base = (base + _random_username_base())[:9]
        return validate_patient_username(base[:64])
    except Exception:
        return _random_username_base()


def generate_unique_patient_username(db: Session, full_name: str) -> str:
    try:
        base = _username_base_from_name(full_name)
    except Exception:
        base = _random_username_base()

    candidate = base[:64]
    suffix = 0
    while True:
        try:
            validate_patient_username(candidate)
            if not db.query(User).filter(User.username == candidate).first():
                return candidate
        except Exception:
            base = _random_username_base()
            candidate = base
            suffix = 0
            continue

        suffix += 1
        suffix_text = str(suffix)
        candidate = f"{base[:64 - len(suffix_text)]}{suffix_text}"


def validate_full_name(full_name: str) -> str:
    clean_full_name = full_name.strip()
    if not clean_full_name:
        raise HTTPException(status_code=400, detail="Full name is required")
    return clean_full_name


def default_patient_context(full_name: str) -> dict:
    preferred_name = full_name.strip().split()[0]
    return {
        "episode_watch_instructions": "",
        "ui_color": "#4A90D9",
        "tts_enabled": True,
        "static_profile": {
            "preferred_name": preferred_name,
            "current_address": "",
            "caregiver_names": [],
            "medical_notes": [],
        },
        "risk_rules": [],
        "trigger_phrases": [
            {"text": "ayuda", "severity": 5},
            {"text": "no s\u00e9 d\u00f3nde estoy", "severity": 5},
        ],
        "assistant_style": {
            "language": "es-ES",
            "tone": "calmado",
            "max_words": 40,
        },
    }


def create_patient_account(
    db: Session,
    *,
    full_name: str,
    username: str | None,
    password: str,
    caregiver_id: int,
    email: str | None = None,
) -> tuple[User, Patient]:
    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    clean_full_name = validate_full_name(full_name)
    manual_username = normalize_username(username)
    clean_username = (
        validate_patient_username(manual_username)
        if manual_username
        else generate_unique_patient_username(db, clean_full_name)
    )
    clean_email = normalize_email(email)

    if clean_email and db.query(User).filter(User.email == clean_email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(User.username == clean_username).first():
        raise HTTPException(status_code=400, detail="Username already registered")

    user = User(
        email=clean_email,
        username=clean_username,
        password_hash=hash_password(password),
        full_name=clean_full_name,
        role="patient",
        caregiver_id=caregiver_id,
    )
    db.add(user)
    db.flush()

    patient = Patient(user_id=user.id)
    db.add(patient)
    db.flush()

    ctx = PatientContext(
        patient_id=patient.id,
        context_json=default_patient_context(clean_full_name),
    )
    db.add(ctx)
    return user, patient
