"""Application configuration, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str = "http://localhost:11434"
    db_path: Path = ROOT_DIR / "data" / "eval_platform.db"
    request_timeout_s: float = 300.0
    max_retries: int = 2
    retry_backoff_s: float = 1.0
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    def public(self) -> dict:
        return {
            "ollama_base_url": self.ollama_base_url,
            "db_path": str(self.db_path),
            "request_timeout_s": self.request_timeout_s,
        }


def load_settings(env: dict | None = None) -> Settings:
    env = os.environ if env is None else env
    defaults = Settings()
    return Settings(
        ollama_base_url=env.get("OLLAMA_BASE_URL", defaults.ollama_base_url).rstrip("/"),
        db_path=Path(env.get("EVAL_DB_PATH", str(defaults.db_path))),
        request_timeout_s=float(env.get("EVAL_REQUEST_TIMEOUT_S", defaults.request_timeout_s)),
        max_retries=int(env.get("EVAL_MAX_RETRIES", defaults.max_retries)),
        retry_backoff_s=float(env.get("EVAL_RETRY_BACKOFF_S", defaults.retry_backoff_s)),
        frontend_dist=Path(env.get("EVAL_FRONTEND_DIST", str(defaults.frontend_dist))),
    )
