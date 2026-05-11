from .auth import router as auth_router
from .patients import router as patients_router
from .audio import router as audio_router
from .alerts import router as alerts_router

__all__ = ["auth_router", "patients_router", "audio_router", "alerts_router"]
