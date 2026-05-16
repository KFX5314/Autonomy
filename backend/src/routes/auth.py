"""
Authentication routes: register and login.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.user import User
from ..schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from ..auth import hash_password, verify_password, create_access_token, get_current_user
from ..services.patient_account_service import (
    normalize_email,
    validate_full_name,
)

router = APIRouter(prefix="/auth", tags=["auth"])


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
    if req.role == "patient":
        raise HTTPException(
            status_code=400,
            detail="Patient accounts must be created by a caregiver",
        )

    email = normalize_email(req.email)

    if not req.password:
        raise HTTPException(status_code=400, detail="Password is required")
    full_name = validate_full_name(req.full_name)

    if not email:
        raise HTTPException(status_code=400, detail="Caregiver must specify email")

    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=email,
        username=None,
        password_hash=hash_password(req.password),
        full_name=full_name,
        role="caregiver",
        caregiver_id=None,
    )
    db.add(user)
    db.flush()

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
