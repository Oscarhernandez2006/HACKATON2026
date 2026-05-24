"""Servicio de extracción de incapacidades — IA (GPT-4o-mini Vision vía GitHub Models)."""

from __future__ import annotations

from app.logger import get_logger
from app.schemas import OcrResult
from app.services.ai_extractor import extract_with_ai
from app.services.downloader import download_adjuntos

logger = get_logger(__name__)


def process_ocr(adjuntos: list[dict], job_uuid: str) -> OcrResult:
    """Procesa los adjuntos de un job: descarga → extracción con IA.

    Args:
        adjuntos: Lista de adjuntos del payload.
        job_uuid: UUID del job para aislar archivos temporales.

    Returns:
        OcrResult con datos extraídos y niveles de confianza.
    """
    logger.info("extraccion_iniciada", total_adjuntos=len(adjuntos))
    file_paths = download_adjuntos(adjuntos, job_uuid)

    result = extract_with_ai(file_paths[0])

    logger.info(
        "extraccion_completa",
        campos_extraidos=len(result.extracted_data.model_dump(exclude_none=True)),
    )

    return result
