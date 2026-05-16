"""Caregiver Expo push token registration."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_caregiver
from ..database import get_db
from ..models.push_token import PushToken
from ..models.user import User
from ..schemas.push import PushTokenIn, PushTokenOut

router = APIRouter(prefix="/push-tokens", tags=["push"])


@router.post("/", response_model=PushTokenOut)
def register_push_token(
    body: PushTokenIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Register or refresh this caregiver device's Expo push token."""
    token_text = body.token.strip()
    token = db.query(PushToken).filter(PushToken.token == token_text).first()
    if token is None:
        token = PushToken(token=token_text)
        db.add(token)

    token.user_id = user.id
    token.platform = (body.platform or "").strip() or None
    token.device_id = (body.device_id or "").strip() or None

    db.commit()
    db.refresh(token)
    return token


@router.delete("/")
def delete_push_token(
    token: str = Query(..., min_length=1, max_length=255),
    db: Session = Depends(get_db),
    user: User = Depends(require_caregiver),
):
    """Remove this caregiver device's push token."""
    row = (
        db.query(PushToken)
        .filter(PushToken.user_id == user.id)
        .filter(PushToken.token == token.strip())
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
    return {"status": "ok"}
