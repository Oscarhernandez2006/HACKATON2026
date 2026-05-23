"""FastAPI app principal — De PDF a Radicado."""

from __future__ import annotations

from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, status

from app.auth import verify_token
from app.config import get_settings
from app.logger import get_logger, setup_logging
from app.schemas import (
    AcceptedResponse,
    AutomationJobRequest,
    JobType,
)
from app.worker import process_automation_job


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown del microservicio."""
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()
    logger.info(
        "microservicio_iniciado",
        env=settings.app_env,
        ocr_engine=settings.ocr_engine,
    )
    yield
    logger.info("microservicio_detenido")


app = FastAPI(
    title="De PDF a Radicado",
    description="Microservicio de automatización para Incapacidades.ai",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health Check ──

@app.get("/health")
async def health():
    """Health check — no requiere autenticación."""
    return {"status": "ok", "service": "pdf-a-radicado"}


# ── Endpoint principal ──

@app.post(
    "/automation/jobs",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(
    request: AutomationJobRequest,
    _token: str = Depends(verify_token),
):
    """Recibe un job de Laravel, lo valida y lo encola.

    Responde HTTP 202 inmediatamente.
    El procesamiento ocurre en segundo plano vía Celery.
    """
    settings = get_settings()
    job = request.job

    # ── Validar callback_url contra allowlist ──
    parsed = urlparse(job.callback_url)
    if parsed.hostname not in settings.allowed_hosts_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"callback_url host '{parsed.hostname}' no está en la allowlist",
        )

    # ── Validaciones según tipo de job ──
    if job.type == JobType.OCR_ADRES_RETHUS:
        if request.caso_preliminar is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="caso_preliminar es requerido para job tipo ocr_adres_rethus",
            )
        if not request.adjuntos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Se requiere al menos un adjunto para OCR",
            )

    elif job.type == JobType.EPS_RADICACION:
        if request.incapacidad is None or request.medico is None or request.radicacion is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="incapacidad, medico y radicacion son requeridos para job tipo eps_radicacion",
            )
        if not request.adjuntos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Se requiere al menos un adjunto para radicación",
            )
        # Validar tamaño de archivos contra límite de la EPS
        max_kb = request.radicacion.max_file_size_kb
        for adj in request.adjuntos:
            if adj.size_kb > max_kb:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Adjunto '{adj.nombre_original}' ({adj.size_kb} KB) "
                        f"excede el límite de {max_kb} KB para {request.radicacion.eps_code}"
                    ),
                )

    # ── Encolar el job en Celery ──
    payload = request.model_dump(mode="json")
    process_automation_job.delay(payload)

    logger.info(
        "job_encolado",
        job_uuid=job.uuid,
        job_type=job.type,
        empresa=request.empresa.razon_social,
        trabajador=f"{request.trabajador.nombres} {request.trabajador.apellidos}",
    )

    return AcceptedResponse(job_uuid=job.uuid)


# ── Adaptadores disponibles ──

@app.get("/adapters")
async def list_available_adapters(_token: str = Depends(verify_token)):
    """Lista todos los adaptadores EPS registrados y su metadata."""
    from app.adapters.registry import list_adapters

    return {"adapters": list_adapters()}


# ── Estado de un job (consulta a Celery) ──

@app.get("/automation/jobs/{job_uuid}/status")
async def get_job_status(job_uuid: str, _token: str = Depends(verify_token)):
    """Consulta el estado de un job en Celery."""
    from celery.result import AsyncResult

    result = AsyncResult(job_uuid, app=process_automation_job.app)

    return {
        "job_uuid": job_uuid,
        "state": result.state,
        "result": result.result if result.ready() else None,
    }
