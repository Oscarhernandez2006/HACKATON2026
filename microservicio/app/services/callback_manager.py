"""Callback Manager — reporta progreso y resultados a Laravel.

Responsabilidades:
- Enviar eventos de progreso en tiempo real (job_received, ocr_started, etc.)
- Enviar resultado final exitoso o fallido
- Validar callback_url contra allowlist
- Firmar callbacks con HMAC (opcional)
- Reintentos automáticos ante fallas de red
"""

from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logger import get_logger
from app.schemas import (
    CompletedCallback,
    ErrorDetail,
    Evidencia,
    FailedCallback,
    JobStatus,
    OcrJobResult,
    ProgressCallback,
    ProgressEvent,
    RadicacionJobResult,
)

logger = get_logger(__name__)


class CallbackManager:
    """Gestiona la comunicación de progreso/resultados hacia Laravel."""

    def __init__(self, callback_url: str, job_uuid: str, incapacidad_uuid: str):
        self.callback_url = callback_url
        self.job_uuid = job_uuid
        self.incapacidad_uuid = incapacidad_uuid
        self._settings = get_settings()
        self._validate_callback_url()

    def _validate_callback_url(self) -> None:
        """Valida que el host del callback_url esté en la allowlist."""
        parsed = urlparse(self.callback_url)
        allowed = self._settings.allowed_hosts_list
        if parsed.hostname not in allowed:
            raise ValueError(
                f"callback_url host '{parsed.hostname}' no permitido. "
                f"Hosts válidos: {allowed}"
            )

    def _sign_payload(self, body: bytes) -> dict[str, str]:
        """Genera firma HMAC-SHA256 del payload si hay secret configurado."""
        headers: dict[str, str] = {}
        secret = self._settings.callback_hmac_secret
        if secret:
            signature = hmac.new(
                secret.encode(), body, hashlib.sha256
            ).hexdigest()
            headers["X-Signature-HMAC"] = signature
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def _send(self, payload: dict) -> None:
        """Envía un callback a Laravel con reintentos automáticos."""
        body = json.dumps(payload, default=str).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.internal_token}",
        }
        headers.update(self._sign_payload(body))

        with httpx.Client(timeout=15.0) as client:
            response = client.post(self.callback_url, content=body, headers=headers)
            response.raise_for_status()

        logger.info(
            "callback_enviado",
            event=payload.get("event"),
            status_code=response.status_code,
        )

    # ── Progreso ──

    def send_progress(
        self,
        event: ProgressEvent,
        progress: int,
        message: str,
        status: JobStatus = JobStatus.RUNNING,
    ) -> None:
        """Envía un evento de progreso a Laravel."""
        callback = ProgressCallback(
            job_uuid=self.job_uuid,
            incapacidad_uuid=self.incapacidad_uuid,
            event=event,
            status=status,
            progress=progress,
            message=message,
        )
        try:
            self._send(callback.model_dump(mode="json"))
        except Exception:
            logger.exception("callback_progreso_fallido", event=event.value)

    # ── Resultado exitoso ──

    def send_success(self, result: OcrJobResult | RadicacionJobResult) -> None:
        """Envía el resultado final exitoso a Laravel."""
        callback = CompletedCallback(
            job_uuid=self.job_uuid,
            incapacidad_uuid=self.incapacidad_uuid,
            result=result,
        )
        try:
            self._send(callback.model_dump(mode="json"))
        except Exception:
            logger.exception("callback_resultado_fallido")

    # ── Error ──

    def send_failure(
        self,
        code: str,
        message: str,
        step: str | None = None,
        evidencias: list[Evidencia] | None = None,
    ) -> None:
        """Envía un callback de error a Laravel."""
        callback = FailedCallback(
            job_uuid=self.job_uuid,
            incapacidad_uuid=self.incapacidad_uuid,
            error=ErrorDetail(code=code, message=message, step=step),
            evidencias=evidencias or [],
        )
        try:
            self._send(callback.model_dump(mode="json"))
        except Exception:
            logger.exception("callback_error_fallido")

    # ── Shortcuts para eventos comunes ──

    def job_received(self) -> None:
        self.send_progress(ProgressEvent.JOB_RECEIVED, 5, "Job recibido", JobStatus.RECEIVED)

    def ocr_started(self) -> None:
        self.send_progress(ProgressEvent.OCR_STARTED, 10, "OCR iniciado")

    def ocr_finished(self) -> None:
        self.send_progress(ProgressEvent.OCR_FINISHED, 30, "OCR completado")

    def adres_started(self) -> None:
        self.send_progress(ProgressEvent.ADRES_STARTED, 35, "Validación ADRES iniciada")

    def adres_finished(self) -> None:
        self.send_progress(ProgressEvent.ADRES_FINISHED, 50, "Validación ADRES completada")

    def rethus_started(self) -> None:
        self.send_progress(ProgressEvent.RETHUS_STARTED, 55, "Validación RETHUS iniciada")

    def rethus_finished(self) -> None:
        self.send_progress(ProgressEvent.RETHUS_FINISHED, 70, "Validación RETHUS completada")

    def rpa_started(self) -> None:
        self.send_progress(ProgressEvent.RPA_STARTED, 75, "RPA en portal EPS iniciado")

    def rpa_finished(self) -> None:
        self.send_progress(ProgressEvent.RPA_FINISHED, 95, "RPA en portal EPS completado")
