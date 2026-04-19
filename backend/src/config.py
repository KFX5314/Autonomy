"""
TFG-DEMENCIA Backend Configuration.
Loaded from environment variables with sensible defaults for local dev.

Any value that is security-sensitive (JWT_SECRET, DB_PASSWORD, CORS_ORIGINS,
PRODUCTION) is validated on startup by server.py when PRODUCTION=1.
"""

import os
from dataclasses import dataclass, field


def _env_csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


# Known insecure development defaults. server.py rejects these when PRODUCTION=1.
DEV_JWT_SECRET = "dev-only-insecure-secret"
DEV_DB_PASSWORD = "tfg_pass_2024"


@dataclass
class Config:
    # Deployment mode. When "1"/"true"/"yes", server.py asserts all critical
    # env vars are set and not the dev defaults. Default off for local dev.
    PRODUCTION: bool = field(default_factory=lambda: os.getenv("PRODUCTION", "0").lower() in ("1", "true", "yes"))

    # Database
    DB_HOST: str = field(default_factory=lambda: os.getenv("DB_HOST", "127.0.0.1"))
    DB_PORT: int = field(default_factory=lambda: int(os.getenv("DB_PORT", "3306")))
    DB_NAME: str = field(default_factory=lambda: os.getenv("DB_NAME", "tfg_demencia"))
    DB_USER: str = field(default_factory=lambda: os.getenv("DB_USER", "tfg_app"))
    DB_PASSWORD: str = field(default_factory=lambda: os.getenv("DB_PASSWORD", DEV_DB_PASSWORD))

    # JWT. In production, JWT_SECRET MUST be set via environment. The dev
    # default is obviously insecure and server.py rejects it when PRODUCTION=1.
    JWT_SECRET: str = field(default_factory=lambda: os.getenv("JWT_SECRET", DEV_JWT_SECRET))
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = field(default_factory=lambda: int(os.getenv("JWT_EXPIRE_MINUTES", "1440")))

    # CORS. Comma-separated allowed origins. Dev defaults cover Expo Go /
    # Metro bundler. In production this MUST be overridden to the caregiver
    # web origin (if any) — the React Native mobile client itself does not
    # need CORS because it is not a browser.
    CORS_ORIGINS: list[str] = field(
        default_factory=lambda: _env_csv(
            "CORS_ORIGINS",
            "http://localhost:19000,http://localhost:19006,http://localhost:8081",
        )
    )

    # Request size / concurrency guards
    MAX_BODY_BYTES: int = field(default_factory=lambda: int(os.getenv("MAX_BODY_BYTES", str(50 * 1024 * 1024))))
    MAX_CONCURRENT_AUDIO: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_AUDIO", "5")))

    # STT
    STT_MODEL: str = field(default_factory=lambda: os.getenv("STT_MODEL", "medium"))
    STT_DEVICE: str = field(default_factory=lambda: os.getenv("STT_DEVICE", "cuda"))
    # Hallucination-mitigation knobs for faster-whisper.
    STT_NO_SPEECH_THRESHOLD: float = field(default_factory=lambda: float(os.getenv("STT_NO_SPEECH_THRESHOLD", "0.7")))
    STT_LOG_PROB_THRESHOLD: float = field(default_factory=lambda: float(os.getenv("STT_LOG_PROB_THRESHOLD", "-0.8")))
    STT_COMPRESSION_RATIO_THRESHOLD: float = field(default_factory=lambda: float(os.getenv("STT_COMPRESSION_RATIO_THRESHOLD", "2.2")))
    STT_MIN_SILENCE_MS: int = field(default_factory=lambda: int(os.getenv("STT_MIN_SILENCE_MS", "300")))
    STT_INITIAL_PROMPT: str = field(default_factory=lambda: os.getenv(
        "STT_INITIAL_PROMPT",
        "Conversación en español entre una persona mayor y su cuidador.",
    ))

    # Speaker diarization (SpeechBrain ECAPA-TDNN).
    # ECAPA is tiny (~14 MB) and CPU inference is fast enough (<100 ms per segment),
    # so we default to CPU to keep CUDA VRAM free for Whisper + LLM.
    SPEAKER_DEVICE: str = field(default_factory=lambda: os.getenv("SPEAKER_DEVICE", "cpu"))

    # LLM Provider: "ollama" | "openai"
    LLM_PROVIDER: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "ollama"))
    LLM_MODEL: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "mistral:7b-instruct"))

    # Ollama
    OLLAMA_URL: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"))

    # OpenAI-compatible API (for scalability demo)
    OPENAI_API_KEY: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    OPENAI_BASE_URL: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))

    # Memory layer.
    # Short-term: rolling window of recent patient utterances injected into the
    # analysis prompt. Long-term: LLM-condensed journal persisted to the DB and
    # exposed to caregivers. Summarization runs in a BackgroundTask so it never
    # adds latency to the audio-chunk response.
    STM_WINDOW_MINUTES: int = field(default_factory=lambda: int(os.getenv("STM_WINDOW_MINUTES", "5")))
    STM_MAX_UTTERANCES: int = field(default_factory=lambda: int(os.getenv("STM_MAX_UTTERANCES", "12")))
    STM_MAX_CHARS: int = field(default_factory=lambda: int(os.getenv("STM_MAX_CHARS", "1500")))
    JOURNAL_INTERVAL_MINUTES: int = field(default_factory=lambda: int(os.getenv("JOURNAL_INTERVAL_MINUTES", "5")))
    JOURNAL_RETENTION_HOURS: int = field(default_factory=lambda: int(os.getenv("JOURNAL_RETENTION_HOURS", "24")))
    JOURNAL_MAX_ENTRIES: int = field(default_factory=lambda: int(os.getenv("JOURNAL_MAX_ENTRIES", "200")))

    # Transcript retention. Cleanup runs piggy-backed on the journal background
    # task, so cost is essentially zero.
    TRANSCRIPT_RETENTION_DAYS: int = field(default_factory=lambda: int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "14")))
    TRANSCRIPT_MAX_ROWS: int = field(default_factory=lambda: int(os.getenv("TRANSCRIPT_MAX_ROWS", "5000")))

    # Alert audio retention.
    # Audio chunks that fire an alert are moved under this dir as
    # <patient_id>/<alert_id><ext>. Non-episode chunks are deleted immediately.
    ALERTS_AUDIO_DIR: str = field(default_factory=lambda: os.getenv(
        "ALERTS_AUDIO_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "alert_audio"),
    ))
    ALERT_AUDIO_ACK_GRACE_HOURS: int = field(default_factory=lambda: int(os.getenv("ALERT_AUDIO_ACK_GRACE_HOURS", "24")))
    ALERT_AUDIO_MAX_DAYS: int = field(default_factory=lambda: int(os.getenv("ALERT_AUDIO_MAX_DAYS", "30")))

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            "?charset=utf8mb4"
        )


config = Config()
