"""
TFG-DEMENCIA Backend Configuration.
Loaded from environment variables with sensible defaults for local dev.
"""

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    # Database
    DB_HOST: str = field(default_factory=lambda: os.getenv("DB_HOST", "127.0.0.1"))
    DB_PORT: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "3306")))
    DB_NAME: str = field(default_factory=lambda: os.getenv("DB_NAME", "tfg_demencia"))
    DB_USER: str = field(default_factory=lambda: os.getenv("DB_USER", "tfg_app"))
    DB_PASSWORD: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", "tfg_pass_2024"))

    # JWT
    JWT_SECRET: str = field(default_factory=lambda: os.getenv("JWT_SECRET", "change-me-in-production"))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = field(default_factory=lambda: int(os.getenv("JWT_EXPIRE_MINUTES", "1440")))

    # STT
    STT_MODEL: str = field(default_factory=lambda: os.getenv("STT_MODEL", "medium"))
    STT_DEVICE: str = field(default_factory=lambda: os.getenv("STT_DEVICE", "cuda"))

    # Speaker diarization (SpeechBrain ECAPA-TDNN).
    # ECAPA is tiny (~14 MB) and CPU inference is fast enough (<100 ms per segment),
    # so we default to CPU to keep CUDA VRAM free for Whisper + LLM.
    SPEAKER_DEVICE: str = field(default_factory=lambda: os.getenv("SPEAKER_DEVICE", "cpu"))

    # LLM Provider: "ollama" | "openai"
    LLM_PROVIDER: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))
    LLM_MODEL: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "phi3:mini"))

    # Ollama
    OLLAMA_URL: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))

    # OpenAI-compatible API (for scalability demo)
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    OPENAI_BASE_URL: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )


config = Config()
