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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables if they don't exist (dev convenience)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created.")
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
