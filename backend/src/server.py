"""
TFG-DEMENCIA Backend - FastAPI application entry point.

Run with:
    uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .routes import auth_router, patients_router, audio_router, alerts_router
from .services.llm import get_llm_provider
from .services.llm.ollama_provider import OllamaProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables if they don't exist (dev convenience)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")

    # Pre-load all heavy models so first request is fast
    logger.info("Warming up models...")

    # 1. Whisper STT
    from .services.stt_service import warmup as warmup_stt
    warmup_stt()

    # 2. Resemblyzer speaker encoder
    from .services.speaker_id_service import warmup as warmup_speaker
    warmup_speaker()

    # 3. Ollama: verify model is available and warm up with a tiny inference
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
    # Shutdown
    logger.info("Shutting down.")


app = FastAPI(
    title="TFG-DEMENCIA API",
    description="AI Assistant backend for dementia/Alzheimer support",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow the Expo dev client
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router)
app.include_router(patients_router)
app.include_router(audio_router)
app.include_router(alerts_router)


@app.get("/health")
async def health():
    llm = get_llm_provider()
    llm_ok = await llm.health_check()
    return {"status": "ok", "llm_available": llm_ok}
