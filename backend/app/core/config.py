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
    # Per-IP cap on the two endpoints whose whole job is a paid Anthropic call.
    # Any slowapi rate-limit string works ("10/hour", "100/day", "5/minute").
    ai_rate_limit: str = "10/hour"
    # /analyze is mostly local CV, but it is not free: the subject locator
    # escalates to a Claude call whenever YOLO-World misses its confidence gate
    # (empirically ~2 photos in 3). Hence a limit — set well above normal use so
    # it only ever stops abuse, not a photographer working through an album.
    analyze_rate_limit: str = "60/hour"
    # How many analyses may run at once. The route handlers are synchronous, so
    # this is the size of the threadpool Starlette runs them in. 0 = auto
    # (cpu_count, clamped to 2-8). Raise it only alongside the memory to match:
    # each in-flight request holds a full-resolution decode.
    analysis_concurrency: int = 0

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
