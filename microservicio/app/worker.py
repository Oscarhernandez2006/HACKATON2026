"""Celery app — configuración y task principal."""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "pdf_a_radicado",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/Bogota",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Reintentos automáticos
    task_default_retry_delay=30,
    task_max_retries=3,
)


@celery_app.task(bind=True, name="process_automation_job", max_retries=3)
def process_automation_job(self, payload: dict) -> dict:
    """Task principal que orquesta el pipeline completo.

    Recibe el payload crudo del endpoint, determina el tipo de job
    y ejecuta el pipeline correspondiente.
    Se implementa en Parte 3 (pipeline) y se conecta aquí.
    """
    from app.pipeline import run_pipeline  # import diferido para evitar circular

    job_uuid = payload["job"]["uuid"]
    job_type = payload["job"]["type"]

    try:
        result = run_pipeline(payload)
        return result
    except Exception as exc:
        # Reintento con backoff exponencial
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
