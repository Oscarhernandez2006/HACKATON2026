"""Pipeline orquestador — conecta OCR, ADRES, RETHUS y RPA.

Cada paso reporta progreso a Laravel via CallbackManager.
"""

from __future__ import annotations

from app.logger import bind_job_context, get_logger
from app.schemas import JobType
from app.services.callback_manager import CallbackManager

logger = get_logger(__name__)


def _build_callback(payload: dict, job_uuid: str, incapacidad_uuid: str) -> CallbackManager:
    """Crea el CallbackManager para este job."""
    return CallbackManager(
        callback_url=payload["job"]["callback_url"],
        job_uuid=job_uuid,
        incapacidad_uuid=incapacidad_uuid,
    )


def run_pipeline(payload: dict) -> dict:
    """Punto de entrada del pipeline. Ejecuta el flujo según job.type."""
    job = payload["job"]
    job_uuid = job["uuid"]
    job_type = job["type"]

    # Determinar incapacidad_uuid según tipo de job
    if job_type == JobType.OCR_ADRES_RETHUS:
        incapacidad_uuid = payload["caso_preliminar"]["uuid"]
    else:
        incapacidad_uuid = payload["incapacidad"]["uuid"]

    bind_job_context(job_uuid, incapacidad_uuid)
    cb = _build_callback(payload, job_uuid, incapacidad_uuid)

    # Notificar recepción
    cb.job_received()
    logger.info("pipeline_started", job_type=job_type)

    try:
        if job_type == JobType.OCR_ADRES_RETHUS:
            return _run_ocr_pipeline(payload, job_uuid, incapacidad_uuid, cb)
        elif job_type == JobType.EPS_RADICACION:
            return _run_radicacion_pipeline(payload, job_uuid, incapacidad_uuid, cb)
        else:
            raise ValueError(f"Tipo de job no soportado: {job_type}")
    except Exception as exc:
        logger.exception("pipeline_failed")
        cb.send_failure(
            code="PIPELINE_ERROR",
            message=str(exc),
            step="pipeline",
        )
        raise


def _run_ocr_pipeline(
    payload: dict, job_uuid: str, incapacidad_uuid: str, cb: CallbackManager
) -> dict:
    """Pipeline: descarga → OCR → ADRES → RETHUS → callback."""
    from app.services.downloader import cleanup_job_files
    from app.services.ocr_service import process_ocr

    adjuntos = payload["adjuntos"]
    trabajador = payload["trabajador"]

    try:
        # ── Paso 1: OCR ──
        cb.ocr_started()
        ocr_result = process_ocr(adjuntos, job_uuid)
        cb.ocr_finished()

        # ── Paso 2: ADRES ──
        cb.adres_started()
        fecha_inicio = ocr_result.extracted_data.fecha_inicio
        from app.services.adres_validator import validate_adres

        adres_result = validate_adres(
            tipo_documento=trabajador["tipo_documento"],
            numero_documento=trabajador["numero_documento"],
            fecha_inicio=fecha_inicio,
            eps_laravel=trabajador["eps_actual"],
        )
        cb.adres_finished()

        # ── Paso 3: RETHUS ──
        cb.rethus_started()
        from app.services.rethus_validator import validate_rethus

        rethus_result = validate_rethus(
            registro_medico=ocr_result.extracted_data.registro_medico,
            medico_nombre=ocr_result.extracted_data.medico_nombre,
        )
        cb.rethus_finished()

        # ── Enviar resultado final ──
        from app.schemas import OcrJobResult

        result = OcrJobResult(
            ocr=ocr_result,
            adres=adres_result,
            rethus=rethus_result,
        )
        cb.send_success(result)

        logger.info("ocr_pipeline_completado")
        return result.model_dump(mode="json")

    finally:
        cleanup_job_files(job_uuid)


def _run_radicacion_pipeline(
    payload: dict, job_uuid: str, incapacidad_uuid: str, cb: CallbackManager
) -> dict:
    """Pipeline: validar tamaño → seleccionar adaptador → RPA → callback."""
    import asyncio
    from pathlib import Path

    from app.adapters.base import AdapterContext
    from app.adapters.registry import get_adapter
    from app.config import get_settings
    from app.schemas import Evidencia, RadicacionJobResult, RadicacionResult
    from app.services.downloader import cleanup_job_files, download_adjuntos

    settings = get_settings()
    radicacion = payload["radicacion"]
    adapter_key = radicacion["adapter_key"]

    try:
        # 1. Obtener adaptador
        adapter = get_adapter(adapter_key)
        logger.info("adaptador_seleccionado", adapter=adapter_key, eps=adapter.eps_name)

        # 2. Descargar adjuntos
        adjuntos_paths = download_adjuntos(payload["adjuntos"], job_uuid)

        # 3. Construir contexto
        evidence_dir = Path(settings.evidence_dir) / job_uuid
        evidence_dir.mkdir(parents=True, exist_ok=True)

        ctx = AdapterContext(
            job_uuid=job_uuid,
            incapacidad_uuid=incapacidad_uuid,
            empresa=payload["empresa"],
            trabajador=payload["trabajador"],
            incapacidad=payload["incapacidad"],
            medico=payload["medico"],
            adjuntos_paths=adjuntos_paths,
            radicacion_config=radicacion,
            evidence_dir=evidence_dir,
        )

        # 4. Ejecutar RPA
        cb.rpa_started()

        # Los adaptadores son async (Playwright), ejecutar en event loop
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(adapter.eps_radicacion(ctx))
        finally:
            loop.close()

        cb.rpa_finished()

        # 5. Construir resultado
        evidencias = [
            Evidencia(tipo=e["tipo"], url=e["path"])
            for e in result.evidencias
        ]

        if result.success:
            rad_result = RadicacionResult(
                status="success",
                numero_radicado=result.numero_radicado,
                mensaje=result.mensaje,
                evidencias=evidencias,
            )
            final = RadicacionJobResult(radicacion=rad_result)
            cb.send_success(final)
            logger.info("radicacion_pipeline_completado", radicado=result.numero_radicado)
            return final.model_dump(mode="json")
        else:
            cb.send_failure(
                code="RPA_FAILED",
                message=result.mensaje,
                step="eps_radicacion",
                evidencias=evidencias,
            )
            return {"status": "failed", "message": result.mensaje}

    except Exception as exc:
        logger.exception("radicacion_pipeline_error")
        cb.send_failure(
            code="RADICACION_ERROR",
            message=str(exc),
            step="radicacion_pipeline",
        )
        raise
    finally:
        cleanup_job_files(job_uuid)


# Placeholders removidos — ADRES y RETHUS ahora usan servicios reales.
