"""Motor OCR — extrae texto de PDFs e imágenes.

Soporta dos engines:
- Tesseract (local, gratuito)
- AWS Textract (cloud, alta precisión para documentos médicos)

Convierte PDFs a imágenes y luego aplica OCR.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)


def extract_text(file_path: Path) -> str:
    """Extrae texto de un archivo PDF o imagen.

    Selecciona el engine según configuración (OCR_ENGINE).
    """
    settings = get_settings()
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        images = _pdf_to_images(file_path)
    elif suffix in (".jpg", ".jpeg", ".png"):
        images = [Image.open(file_path)]
    else:
        raise ValueError(f"Formato no soportado para OCR: {suffix}")

    if settings.ocr_engine == "textract":
        return _ocr_textract(file_path)
    else:
        return _ocr_tesseract(images)


def _pdf_to_images(pdf_path: Path) -> list[Image.Image]:
    """Convierte un PDF a lista de imágenes PIL (una por página)."""
    from pdf2image import convert_from_path

    logger.info("pdf_a_imagenes", archivo=pdf_path.name)
    images = convert_from_path(str(pdf_path), dpi=300)
    logger.info("pdf_convertido", paginas=len(images))
    return images


def _ocr_tesseract(images: list[Image.Image]) -> str:
    """Aplica Tesseract OCR a una lista de imágenes."""
    import pytesseract

    logger.info("ocr_tesseract_iniciado", paginas=len(images))
    texts = []
    for i, img in enumerate(images):
        text = pytesseract.image_to_string(img, lang="spa")
        texts.append(text)
        logger.debug("pagina_procesada", pagina=i + 1, caracteres=len(text))

    full_text = "\n\n".join(texts)
    logger.info("ocr_tesseract_completado", caracteres_total=len(full_text))
    return full_text


def _ocr_textract(file_path: Path) -> str:
    """Aplica AWS Textract a un archivo PDF o imagen."""
    import boto3

    settings = get_settings()
    logger.info("ocr_textract_iniciado", archivo=file_path.name)

    client = boto3.client(
        "textract",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    file_bytes = file_path.read_bytes()
    response = client.detect_document_text(
        Document={"Bytes": file_bytes}
    )

    lines = []
    for block in response.get("Blocks", []):
        if block["BlockType"] == "LINE":
            lines.append(block["Text"])

    full_text = "\n".join(lines)
    logger.info("ocr_textract_completado", caracteres_total=len(full_text), lineas=len(lines))
    return full_text
