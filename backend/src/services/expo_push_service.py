"""Expo push notification helpers for caregiver alert delivery."""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session

from ..config import config
from ..database import SessionLocal
from ..models.push_token import PushToken

logger = logging.getLogger(__name__)


_INVALID_TOKEN_ERRORS = {"DeviceNotRegistered"}


def _trim(value: str, max_chars: int) -> str:
    value = " ".join((value or "").split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


def notify_caregiver_alert(
    caregiver_id: int,
    alert_id: int,
    patient_name: str,
    severity: int,
    reason: str,
    db: Session | None = None,
) -> int:
    """Send a best-effort Expo push notification for a new alert.

    Returns the number of target tokens attempted. All provider/network errors
    are logged and swallowed so alert creation never depends on push delivery.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        tokens = (
            db.query(PushToken)
            .filter(PushToken.user_id == caregiver_id)
            .order_by(PushToken.updated_at.desc(), PushToken.id.desc())
            .all()
        )
        if not tokens:
            return 0

        title = f"Alerta de {patient_name or 'paciente'}"
        body = _trim(f"Sev. {severity}/5: {reason}", 160)
        messages = [
            {
                "to": token.token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": {
                    "type": "alert",
                    "alert_id": alert_id,
                    "severity": severity,
                },
            }
            for token in tokens
        ]

        response = httpx.post(
            config.EXPO_PUSH_URL,
            json=messages,
            timeout=config.EXPO_PUSH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("data", []) if isinstance(payload, dict) else []

        deleted = 0
        for token, result in zip(tokens, results):
            if not isinstance(result, dict) or result.get("status") != "error":
                continue
            details = result.get("details") or {}
            if details.get("error") in _INVALID_TOKEN_ERRORS:
                db.delete(token)
                deleted += 1

        if deleted:
            db.commit()
        return len(tokens)
    except Exception as exc:
        logger.warning("Expo push notification failed for alert %s: %s", alert_id, exc)
        db.rollback()
        return 0
    finally:
        if owns_session:
            db.close()
