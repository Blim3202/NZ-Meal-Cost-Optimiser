"""FastAPI settings: loads .env from the repo root and exposes Supabase config."""
from pydantic_settings import BaseSettings
from pydantic import Field

from NZMealOptimiser import PROJECT_ROOT


class Settings(BaseSettings):
    """App settings loaded from .env; ignores unknown keys."""
    model_config = {
        # Load .env from the repo root; ignore extra env vars.
        "env_file": (PROJECT_ROOT / ".env",),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # Supabase connection credentials from environment.
    SUPABASE_URL: str = Field(default="", description="Supabase project URL")
    SUPABASE_SECRET_KEY: str = Field(default="", description="Supabase service_role key")

    # Size of the background search thread pool (main.py _THREAD_POOL). The
    # executor is created at import time and cannot be resized live, so
    # changes require a server restart. Exposed in GET /system-info.
    WEB_MAX_WORKERS: int = Field(default=20, ge=1, le=64, description="Search thread-pool size (restart required)")

    @property
    def supabase_enabled(self) -> bool:
        """True if both Supabase URL and key are set."""
        return bool(self.SUPABASE_URL and self.SUPABASE_SECRET_KEY)


# Singleton settings instance used across the app.
settings = Settings()
