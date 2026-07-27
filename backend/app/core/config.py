from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load backend/.env into os.environ at import time so raw os.environ.get(...)
# reads work under uvicorn — not just under the eval harness (which loads it
# explicitly). The AI critique layer (ai_client.py) and the VLM subject-locator
# tier read ANTHROPIC_API_KEY directly from the environment, and pydantic's
# env_file only populates declared Settings fields, not os.environ.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "FrameGrader"
    allowed_origins: str = "http://localhost:5173"
    max_upload_mb: int = 25

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
