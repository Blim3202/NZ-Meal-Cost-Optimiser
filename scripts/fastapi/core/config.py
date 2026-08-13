from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


_FASTAPI_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = {
        "env_file": (_FASTAPI_DIR / ".env",),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    SUPABASE_URL: str = Field(default="", description="Supabase project URL")
    SUPABASE_SECRET_KEY: str = Field(default="", description="Supabase service_role key")

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_SECRET_KEY)


settings = Settings()
