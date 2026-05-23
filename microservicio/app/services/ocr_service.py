"""Servicio OCR unificado — orquesta descarga, OCR y extracción.

Punto de entrada único que el pipeline llama para procesar los adjuntos
y obtener datos estructurados con confianzas.
"""

from __future__ import annotations

from pathlib import Path

from app.logger import get_logger
from app.schemas import OcrExtractedData, OcrResult
from app.services.downloader import cleanup_job_files, download_adjuntos
from app.services.ocr_engine import extract_text
from app.services.ocr_extractor import ExtractionResult, extract_structured_data

logger = get_logger(__name__)


def process_ocr(adjuntos: list[dict], job_uuid: str) -> OcrResult:
    """Procesa los adjuntos de un job: descarga → OCR → extracción estructurada.

    Args:
        adjuntos: Lista de adjuntos del payload (dicts con url_temporal, nombre_original, etc.)
        job_uuid: UUID del job para aislar archivos temporales.

    Returns:
        OcrResult con datos extraídos y niveles de confianza.
    """
    # 1. Descargar archivos
    logger.info("ocr_descarga_iniciada", total_adjuntos=len(adjuntos))
    file_paths = download_adjuntos(adjuntos, job_uuid)

    # 2. OCR sobre cada archivo
    all_text = []
    for path in file_paths:
        logger.info("ocr_procesando_archivo", archivo=path.name)
        text = extract_text(path)
        all_text.append(text)

    combined_text = "\n\n===SIGUIENTE DOCUMENTO===\n\n".join(all_text)

    # 3. Extracción estructurada
    extraction: ExtractionResult = extract_structured_data(combined_text)

    logger.info(
        "ocr_proceso_completo",
        campos_extraidos=len(extraction.data.model_dump(exclude_none=True)),
        campos_revision=extraction.needs_review,
    )

    return OcrResult(
        status="processed",
        extracted_data=extraction.data,
        confidence=extraction.confidence,
    )
