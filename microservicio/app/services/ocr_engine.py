"""Motor OCR — extrae texto de PDFs e imágenes.

Soporta dos engines:
- Tesseract (local, gratuito)
- AWS Textract (cloud, alta precisión para documentos médicos)

Convierte PDFs a imágenes con PyMuPDF y luego aplica OCR.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)


def extract_text(file_path: Path) -> str:
    """Extrae texto de un archivo PDF o imagen.

    Para PDFs con texto embebido usa PyMuPDF directamente (rápido, sin OCR).
    Para imágenes o PDFs escaneados usa Tesseract OCR.
    """
    settings = get_settings()
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        # Intentar extracción directa con PyMuPDF primero
        text = _extract_pdf_text(file_path)
        if len(text.strip()) > 50:
            return text
        # Si no hay texto embebido, caer a OCR
        logger.info("pdf_sin_texto_embebido_usando_ocr", archivo=file_path.name)
        images = _pdf_to_images(file_path)
        return _ocr_tesseract(images)
    elif suffix in (".jpg", ".jpeg", ".png"):
        images = [Image.open(file_path)]
        return _ocr_tesseract(images)
    else:
        raise ValueError(f"Formato no soportado para OCR: {suffix}")


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extrae texto directamente de un PDF con PyMuPDF (sin OCR)."""
    import fitz

    logger.info("pdf_extraccion_directa", archivo=pdf_path.name)
    doc = fitz.open(str(pdf_path))
    texts = []
    for i in range(len(doc)):
        page = doc[i]
        text = page.get_text()
        texts.append(text)
    doc.close()
    full_text = "\n\n".join(texts)
    logger.info("pdf_texto_extraido", caracteres=len(full_text), paginas=len(texts))
    return full_text


def _pdf_to_images(pdf_path: Path) -> list[Image.Image]:
    """Convierte un PDF a lista de imágenes PIL con PyMuPDF (sin poppler)."""
    import fitz  # PyMuPDF
    import io

    logger.info("pdf_a_imagenes", archivo=pdf_path.name)
    doc = fitz.open(str(pdf_path))
    images = []
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))
        images.append(img)
    doc.close()
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
