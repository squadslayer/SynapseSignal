"""
SynapseSignal Control Engine — Configuration
=============================================
Centralized configuration using Pydantic BaseSettings.
All values can be overridden via environment variables.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application-wide settings, loaded from env vars or .env file."""

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # ── State Management ────────────────────────────────────────────────
    # Maximum age (seconds) before a state is considered stale.
    STALENESS_THRESHOLD_SEC: float = 5.0

    # Minimum time (seconds) a sector must remain green before switching.
    # Prevents erratic flip-flopping between sectors.
    MIN_DWELL_TIME_SEC: float = 2.0

    # Maximum allowed gap (seconds) between consecutive frames before
    # the engine treats it as a "skipped frame" event.
    MAX_FRAME_GAP_SEC: float = 3.0

    # ── Fallback / Safety ───────────────────────────────────────────────
    # Duration (seconds) of the default cycle when failsafe is active.
    FALLBACK_CYCLE_DURATION_SEC: float = 30.0

    # ── Database (Dev 5) ────────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "synapsesignal"
    DB_USER: str = "synapse_user"
    DB_PASS: str = "strongpassword"

    # ── API ──────────────────────────────────────────────────────────────
    API_PREFIX: str = "/api/v1"

    model_config = {"env_prefix": "SYNAPSE_", "env_file": ".env"}


# Singleton instance used across the application.
settings = Settings()
