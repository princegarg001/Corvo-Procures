"""12-factor settings read from the environment (PLAN §14). No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    """Read KEY=VALUE lines from the repo-root .env (never overrides real environment variables)."""
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalise_db_url(url: str) -> str:
    """Accept Neon/Supabase/Render style URLs and use the psycopg 3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: normalise_db_url(
        os.getenv("DATABASE_URL") or f"sqlite:///{(REPO_ROOT / 'backend' / 'var' / 'corvo.db').as_posix()}"))
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))
    groq_api_key: str = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"))
    llm_timeout_s: float = field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_S", "20")))
    app_tz: str = field(default_factory=lambda: os.getenv("APP_TZ", "Asia/Kolkata"))
    kit_dir: Path = field(default_factory=lambda: Path(os.getenv("KIT_DIR", str(REPO_ROOT / "data" / "kit"))))
    policy_dir: Path = field(default_factory=lambda: Path(os.getenv("POLICY_DIR", str(REPO_ROOT / "policies"))))
    register_as_of: date = field(default_factory=lambda: date.fromisoformat(os.getenv("REGISTER_AS_OF", "2026-10-31")))
    seed_on_start: bool = field(default_factory=lambda: _bool("SEED_ON_START", True))
    seed_demo_run: bool = field(default_factory=lambda: _bool("SEED_DEMO_RUN", True))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "10")))
    static_dir: Path = field(default_factory=lambda: Path(os.getenv("STATIC_DIR", str(REPO_ROOT / "frontend" / "dist"))))
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", True))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def llm_available(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def today() -> date:
    """Today's date in the app timezone (Asia/Kolkata); APP_TODAY=YYYY-MM-DD pins it for demos/tests."""
    return now_local().date()


def now_local():  # type: ignore[no-untyped-def]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(get_settings().app_tz))
    pinned = os.getenv("APP_TODAY")
    if pinned:
        d = date.fromisoformat(pinned)
        now = now.replace(year=d.year, month=d.month, day=d.day)
    return now


def reset_settings() -> None:
    global _settings
    _settings = None
