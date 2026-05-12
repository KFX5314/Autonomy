"""
TFG-DEMENCIA Backend - FastAPI application entry point.

Run with:
    uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config, DEV_JWT_SECRET, DEV_DB_PASSWORD
from .database import engine, Base
from .middleware.size_limit import BodySizeLimitMiddleware
from .routes import auth_router, patients_router, audio_router, alerts_router
from .services.llm import get_llm_provider
from .services.llm.ollama_provider import OllamaProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _enforce_production_safety() -> None:
    """Fail loudly if we're starting in PRODUCTION mode with insecure defaults.

    Caught here (not at import time) so dev boots keep working.
    """
    if not config.PRODUCTION:
        if config.JWT_SECRET == DEV_JWT_SECRET:
            logger.warning(
                "⚠  JWT_SECRET is the dev default. DO NOT deploy like this. "
                "Set JWT_SECRET to a 32+ byte random value before production."
            )
        return

    problems: list[str] = []
    if not config.JWT_SECRET or config.JWT_SECRET == DEV_JWT_SECRET:
        problems.append("JWT_SECRET is unset or still the dev placeholder")
    if len(config.JWT_SECRET) < 32:
        problems.append("JWT_SECRET is shorter than 32 characters")
    if config.DB_PASSWORD == DEV_DB_PASSWORD:
        problems.append("DB_PASSWORD is still the dev default")
    if any(o.strip() == "*" for o in config.CORS_ORIGINS):
        problems.append("CORS_ORIGINS contains '*' (wildcard is unsafe with credentials)")
    if not config.CORS_ORIGINS:
        problems.append("CORS_ORIGINS is empty")

    if problems:
        msg = "Refusing to start with insecure production configuration:\n  - " + "\n  - ".join(problems)
        raise RuntimeError(msg)


def _migrate_alert_audio_columns() -> None:
    """Add new alert columns on pre-existing DBs. No-op if columns already exist."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("alerts")}
    except Exception:
        return
    stmts: list[str] = []
    if "audio_path" not in cols:
        stmts.append("ALTER TABLE alerts ADD COLUMN audio_path VARCHAR(512) NULL")
    if "acknowledged_at" not in cols:
        stmts.append("ALTER TABLE alerts ADD COLUMN acknowledged_at TIMESTAMP NULL")
    if stmts:
        with engine.begin() as conn:
            for s in stmts:
                try:
                    conn.execute(text(s))
                    logger.info(f"Migration: {s}")
                except Exception as e:
                    logger.warning(f"Migration failed ({s}): {e}")


def _migrate_user_identifier_columns() -> None:
    """Allow patients to authenticate by username while caregivers keep email."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    try:
        cols = {c["name"]: c for c in insp.get_columns("users")}
    except Exception:
        return

    stmts: list[str] = []
    if "username" not in cols:
        stmts.append("ALTER TABLE users ADD COLUMN username VARCHAR(64) NULL UNIQUE")
    if "email" in cols and not cols["email"].get("nullable", True):
        stmts.append("ALTER TABLE users MODIFY email VARCHAR(255) NULL")

    if stmts:
        with engine.begin() as conn:
            for s in stmts:
                try:
                    conn.execute(text(s))
                    logger.info(f"Migration: {s}")
                except Exception as e:
                    logger.warning(f"Migration failed ({s}): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _enforce_production_safety()

    Base.metadata.create_all(bind=engine)
    _migrate_user_identifier_columns()
    _migrate_alert_audio_columns()
    logger.info("Database tables verified/created.")

    from .services.alert_audio_retention import sweep_expired_alert_audio
    sweep_expired_alert_audio()

    if os.getenv("TFG_SKIP_MODEL_WARMUP") == "1":
        logger.warning("Skipping model warm-up because TFG_SKIP_MODEL_WARMUP=1.")
    else:
        logger.info("Warming up models...")

        from .services.stt_service import warmup as warmup_stt
        warmup_stt()

        from .services.speaker_id_service import warmup as warmup_speaker
        warmup_speaker()

        llm = get_llm_provider()
        if isinstance(llm, OllamaProvider):
            await llm.check_model()
            try:
                logger.info("Warming up Ollama (first inference)...")
                await llm.generate("Responde OK.", "test")
                logger.info("Ollama warm-up done.")
            except Exception as e:
                logger.warning(f"Ollama warm-up inference failed: {e}")

    logger.info("All models ready. Server accepting requests.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="TFG-DEMENCIA API",
    description="AI Assistant backend for dementia/Alzheimer support",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allowlist from config (env CORS_ORIGINS, comma-separated).
# A wildcard "*" combined with credentials is rejected at startup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Reject oversized request bodies before they hit the handlers.
app.add_middleware(BodySizeLimitMiddleware)

app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(audio_router)
app.include_router(alerts_router)


@app.get("/health")
async def health():
    if os.getenv("TFG_SKIP_HEALTH_LLM") == "1":
        return {"status": "ok", "llm_available": True}
    llm = get_llm_provider()
    llm_ok = await llm.health_check()
    return {"status": "ok", "llm_available": llm_ok}
