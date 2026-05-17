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
from .routes import auth_router, patients_router, audio_router, alerts_router, push_tokens_router
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


def _verify_database_schema() -> None:
    """Fail fast when the MariaDB schema was not initialized from init_db.sql."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    try:
        existing_tables = set(insp.get_table_names())
    except Exception as exc:
        raise RuntimeError(
            "No se pudo inspeccionar la base de datos. Comprueba que MariaDB "
            "esta levantado y ejecuta: mariadb -u root -p < backend/init_db.sql"
        ) from exc

    expected = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }
    missing_tables = sorted(set(expected) - existing_tables)
    missing_columns: list[str] = []
    for table_name, expected_columns in expected.items():
        if table_name not in existing_tables:
            continue
        actual_columns = {column["name"] for column in insp.get_columns(table_name)}
        for column_name in sorted(expected_columns - actual_columns):
            missing_columns.append(f"{table_name}.{column_name}")

    if missing_tables or missing_columns:
        details: list[str] = []
        if missing_tables:
            details.append("tablas faltantes: " + ", ".join(missing_tables))
        if missing_columns:
            details.append("columnas faltantes: " + ", ".join(missing_columns))
        raise RuntimeError(
            "El esquema de MariaDB no coincide con el esquema canonico del proyecto. "
            "La base de datos de entrega es reinicializable; ejecuta "
            "`mariadb -u root -p < backend/init_db.sql` y vuelve a arrancar. "
            + " | ".join(details)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _enforce_production_safety()

    _verify_database_schema()
    logger.info("Database schema verified.")

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
app.include_router(push_tokens_router)


@app.get("/health")
async def health():
    if os.getenv("TFG_SKIP_HEALTH_LLM") == "1":
        return {"status": "ok", "llm_available": True}
    llm = get_llm_provider()
    llm_ok = await llm.health_check()
    return {"status": "ok", "llm_available": llm_ok}
