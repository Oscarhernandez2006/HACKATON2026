"""Servicio OCR unificado — orquesta descarga y extracción con IA o Tesseract.

Motor por defecto: IA (GPT-4o Vision vía GitHub Models) → envía la imagen directo al modelo.
Fallback: Tesseract + regex (si no hay GITHUB_TOKEN configurado).
"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.logger import get_logger
from app.schemas import OcrExtractedData, OcrResult
from app.services.downloader import download_adjuntos

logger = get_logger(__name__)


def process_ocr(adjuntos: list[dict], job_uuid: str) -> OcrResult:
    """Procesa los adjuntos de un job: descarga → extracción con IA o OCR.

    Si OCR_ENGINE=ai → usa GPT-4o Vision (recomendado).
    Si OCR_ENGINE=tesseract → usa Tesseract + regex.
    Si OCR_ENGINE=textract → usa AWS Textract + regex.

    Args:
        adjuntos: Lista de adjuntos del payload.
        job_uuid: UUID del job para aislar archivos temporales.

    Returns:
        OcrResult con datos extraídos y niveles de confianza.
    """
    settings = get_settings()

    # 1. Descargar archivos
    logger.info("ocr_descarga_iniciada", total_adjuntos=len(adjuntos))
    file_paths = download_adjuntos(adjuntos, job_uuid)

    # 2. Extraer según el motor configurado
    if settings.ocr_engine == "ai":
        return _extract_with_ai(file_paths)
    else:
        return _extract_with_ocr(file_paths)


def _extract_with_ai(file_paths: list[Path]) -> OcrResult:
    """Extracción con IA (GPT-4o Vision) — envía imagen directo al modelo."""
    from app.services.ai_extractor import extract_with_ai

    logger.info("extraccion_ia_iniciada", motor="gpt4o_vision", archivos=len(file_paths))

    # Procesar el primer documento (principal)
    # Si hay múltiples, se puede iterar o combinar
    result = extract_with_ai(file_paths[0])

    logger.info(
        "extraccion_ia_completa",
        campos_extraidos=len(result.extracted_data.model_dump(exclude_none=True)),
    )

    return result


def _extract_with_ocr(file_paths: list[Path]) -> OcrResult:
    """Extracción con OCR tradicional (Tesseract/Textract) + regex."""
    from app.services.ocr_engine import extract_text
    from app.services.ocr_extractor import ExtractionResult, extract_structured_data

    logger.info("extraccion_ocr_iniciada", motor="tesseract")

    all_text = []
    for path in file_paths:
        logger.info("ocr_procesando_archivo", archivo=path.name)
        text = extract_text(path)
        all_text.append(text)

    combined_text = "\n\n===SIGUIENTE DOCUMENTO===\n\n".join(all_text)
    extraction: ExtractionResult = extract_structured_data(combined_text)

    logger.info(
        "extraccion_ocr_completa",
        campos_extraidos=len(extraction.data.model_dump(exclude_none=True)),
        campos_revision=extraction.needs_review,
    )

    return OcrResult(
        status="processed",
        extracted_data=extraction.data,
        confidence=extraction.confidence,
    )

    return OcrResult(
        status="processed",
        extracted_data=extraction.data,
        confidence=extraction.confidence,
    )
