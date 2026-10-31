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
    # enterprise providers (retries happen inside the adapters, before the first byte)
    provider_max_retries: int = 4
    provider_backoff_s: float = 1.0
    provider_backoff_cap_s: float = 30.0
    frontend_dist: Path = ROOT_DIR / "frontend" / "dist"
    # gateway-model-sync (add-gateway-model-sync): None disables sync entirely ("skipped", never an error) - a
    # valid deployment choice for an installation with no task-routed agents yet. The admin credential itself
    # (EVAL_GATEWAY_ADMIN_KEY) is read directly from the environment in app.core.gateway_sync, never stored here
    # or logged, the same discipline KeyProvider already applies to every other credential this platform holds.
    gateway_url: str | None = None
    gateway_sync_timeout_s: float = 5.0
    # add-otel-tracing: OTLP gRPC endpoint for the Runner's own spans (e.g. "http://localhost:4317",
    # the observability stack's otel-collector). None disables tracing entirely - a graceful no-op,
    # the same "unset = off" convention as gateway_url above.
    otel_endpoint: str | None = None
    # add-otel-tracing: Tempo's own query API (e.g. "http://localhost:3200"), used only by the
    # backend's own `/api/traces/{trace_id}` proxy - the browser never talks to Tempo directly.
    # None disables the trace-tree view entirely (a graceful "not configured", never an error).
    tempo_base_url: str | None = None
    # add-agent-playground: symmetric key for `app.core.secrets` (Fernet), encrypting a
    # playground-eligible agent's stored spawn credentials (design.md D2). None disables the whole
    # playground-eligibility feature - marking an agent eligible is rejected with a clear error
    # naming this variable, the same "unset = off" convention as gateway_url/otel_endpoint above,
    # rather than storing something that could never be decrypted back.
    playground_secret_key: str | None = None
    # add-agent-playground: this backend's own address, as a spawned agent subprocess's `--platform-url`
    # (the one the spawning operator would type by hand) - only meaningful because the backend, not an
    # operator, is the one assembling that command line now. Defaults to the same address this repo's
    # own docs use for a locally-run dev server.
    platform_self_url: str = "http://127.0.0.1:8000"

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
        provider_max_retries=int(env.get("EVAL_PROVIDER_MAX_RETRIES", defaults.provider_max_retries)),
        provider_backoff_s=float(env.get("EVAL_PROVIDER_BACKOFF_S", defaults.provider_backoff_s)),
        frontend_dist=Path(env.get("EVAL_FRONTEND_DIST", str(defaults.frontend_dist))),
        gateway_url=env.get("EVAL_GATEWAY_URL", defaults.gateway_url) or None,
        gateway_sync_timeout_s=float(env.get("EVAL_GATEWAY_SYNC_TIMEOUT_S", defaults.gateway_sync_timeout_s)),
        otel_endpoint=env.get("EVAL_OTEL_ENDPOINT", defaults.otel_endpoint) or None,
        tempo_base_url=env.get("EVAL_TEMPO_BASE_URL", defaults.tempo_base_url) or None,
        playground_secret_key=env.get("EVAL_SECRET_KEY", defaults.playground_secret_key) or None,
        platform_self_url=env.get("EVAL_PLATFORM_SELF_URL", defaults.platform_self_url),
    )
