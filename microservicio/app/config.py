"""Configuración centralizada del microservicio."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──
    app_env: str = "development"
    app_debug: bool = False
    log_level: str = "INFO"

    # ── Auth ──
    internal_token: str = "dev-token"

    # ── Redis / Celery ──
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── IA Extractor (GitHub Models) ──
    github_token: str | None = None
    github_models_endpoint: str = "https://models.github.ai/inference"
    github_models_model: str = "openai/gpt-4o-mini"

    # ── Validaciones externas ──
    adres_base_url: str = "https://appweb.adres.gov.co"
    rethus_base_url: str = "https://rfrr.minsalud.gov.co"

    # ── Callback Security ──
    callback_allowed_hosts: str = "localhost"
    callback_hmac_secret: str = ""

    # ── Playwright ──
    playwright_headless: bool = True
    playwright_timeout: int = 60_000

    # ── Concurrencia ──
    celery_worker_concurrency: int = 4
    max_browser_contexts: int = 4

    # ── Storage ──
    temp_dir: str = "/tmp/pdf-a-radicado"
    evidence_dir: str = "/tmp/pdf-a-radicado/evidencias"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.callback_allowed_hosts.split(",") if h.strip()]

    def ensure_dirs(self) -> None:
        Path(self.temp_dir).mkdir(parents=True, exist_ok=True)
        Path(self.evidence_dir).mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
