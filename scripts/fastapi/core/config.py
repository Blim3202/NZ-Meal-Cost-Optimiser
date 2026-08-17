"""FastAPI settings: loads .env from fastapi parent and exposes Supabase config."""
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


# Resolve fastapi directory for relative .env loading.
_FASTAPI_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """App settings loaded from .env; ignores unknown keys."""
    model_config = {
        # Load .env relative to fastapi folder; ignore extra env vars.
        "env_file": (_FASTAPI_DIR / ".env",),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # Supabase connection credentials from environment.
    SUPABASE_URL: str = Field(default="", description="Supabase project URL")
    SUPABASE_SECRET_KEY: str = Field(default="", description="Supabase service_role key")

    @property
    def supabase_enabled(self) -> bool:
        """True if both Supabase URL and key are set."""
        return bool(self.SUPABASE_URL and self.SUPABASE_SECRET_KEY)


# Singleton settings instance used across the app.
settings = Settings()
