"""Extractor de documentos con IA (GPT-4o Vision vía GitHub Models).

Envía la imagen/PDF del certificado de incapacidad a GPT-4o Vision
y recibe los datos estructurados con confianza por campo.

Ventajas sobre OCR+regex:
- Entiende contexto, tablas, sellos y texto manuscrito
- No necesita patrones regex por EPS
- Maneja variaciones de formato automáticamente
- Detecta campos ambiguos y reporta baja confianza
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
from pdf2image import convert_from_path
from PIL import Image
import io

from app.config import get_settings
from app.logger import get_logger
from app.schemas import OcrExtractedData, OcrResult

logger = get_logger(__name__)

# Prompt de extracción — le dice al modelo exactamente qué extraer
EXTRACTION_PROMPT = """Eres un experto en documentos médicos colombianos de incapacidades laborales.

Analiza la imagen del certificado de incapacidad y extrae los siguientes datos en formato JSON.

CAMPOS A EXTRAER:
- numero_incapacidad: Número o código del certificado de incapacidad
- tipo: Tipo de incapacidad (ENFERMEDAD_GENERAL, ACCIDENTE_TRABAJO, LICENCIA_MATERNIDAD, LICENCIA_PATERNIDAD, ENFERMEDAD_LABORAL)
- origen: COMUN o LABORAL
- fecha_expedicion: Fecha de expedición del documento (formato YYYY-MM-DD)
- fecha_atencion: Fecha de atención médica (formato YYYY-MM-DD)
- fecha_inicio: Fecha de inicio de la incapacidad (formato YYYY-MM-DD)
- fecha_fin: Fecha de fin de la incapacidad (formato YYYY-MM-DD)
- dias: Número de días de incapacidad (entero)
- diagnostico_codigo: Código CIE-10 del diagnóstico (ej: M545, J060)
- diagnostico_descripcion: Descripción del diagnóstico
- eps_detectada: Nombre de la EPS (SANITAS, SURA, COMPENSAR, NUEVA_EPS, SALUD_TOTAL, COOSALUD, FAMISANAR, MUTUAL_SER)
- medico_nombre: Nombre completo del médico tratante
- registro_medico: Número de registro médico o tarjeta profesional
- ips: Nombre de la IPS o institución
- es_prorroga: true si es prórroga/extensión de incapacidad anterior, false si no

REGLAS:
- Si no puedes leer un campo con certeza, pon null
- Las fechas SIEMPRE en formato YYYY-MM-DD
- Los nombres de EPS deben normalizarse a los códigos indicados arriba
- Si ves "Suramericana" es SURA, "Nueva EPS" es NUEVA_EPS, "Salud Total" es SALUD_TOTAL, "Mutual Ser" es MUTUAL_SER
- El código CIE-10 tiene formato letra + números (ej: M545, J060, K359)

Además, para cada campo extraído, indica tu nivel de confianza (0.0 a 1.0).

Responde SOLO con JSON válido, sin markdown, sin explicaciones. Estructura:
{
  "extracted_data": { ... los campos ... },
  "confidence": { "campo": 0.95, ... },
  "needs_review": ["campo1", "campo2"],
  "notas": "observaciones relevantes sobre el documento"
}"""


def extract_with_ai(file_path: Path) -> OcrResult:
    """Extrae datos estructurados de un documento usando GPT-4o Vision.

    Args:
        file_path: Ruta al archivo PDF, JPG o PNG.

    Returns:
        OcrResult con datos extraídos y confianzas.
    """
    settings = get_settings()

    # Convertir a imágenes base64
    images_b64 = _prepare_images(file_path)
    logger.info("imagenes_preparadas", total=len(images_b64), archivo=file_path.name)

    # Construir mensaje para OpenAI
    content = _build_message_content(images_b64)

    # Llamar a OpenAI Vision (GitHub Models)
    response_data = _call_openai(content, settings)

    # Parsear respuesta
    return _parse_response(response_data)


def _prepare_images(file_path: Path) -> list[dict]:
    """Convierte el archivo a imágenes base64 para enviar al modelo."""
    suffix = file_path.suffix.lower()
    images_b64 = []

    if suffix == ".pdf":
        # Convertir PDF a imágenes (300 DPI para buena calidad)
        pil_images = convert_from_path(str(file_path), dpi=300)
        for i, img in enumerate(pil_images):
            b64 = _pil_to_base64(img)
            images_b64.append({"type": "image", "data": b64, "media_type": "image/png"})
            logger.debug("pagina_convertida", pagina=i + 1)
    elif suffix in (".jpg", ".jpeg"):
        b64 = base64.b64encode(file_path.read_bytes()).decode()
        images_b64.append({"type": "image", "data": b64, "media_type": "image/jpeg"})
    elif suffix == ".png":
        b64 = base64.b64encode(file_path.read_bytes()).decode()
        images_b64.append({"type": "image", "data": b64, "media_type": "image/png"})
    else:
        raise ValueError(f"Formato no soportado: {suffix}")

    return images_b64


def _pil_to_base64(img: Image.Image) -> str:
    """Convierte una imagen PIL a base64 PNG."""
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def _build_message_content(images_b64: list[dict]) -> list[dict]:
    """Construye el contenido del mensaje para OpenAI con imágenes + prompt."""
    content = []

    # Agregar cada imagen como image_url con base64
    for img in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['media_type']};base64,{img['data']}",
            },
        })

    # Agregar el prompt de extracción
    content.append({
        "type": "text",
        "text": EXTRACTION_PROMPT,
    })

    return content


def _call_openai(content: list[dict], settings) -> dict:
    """Llama a la API de OpenAI (GitHub Models) con visión."""
    api_key = settings.github_token
    if not api_key:
        raise ValueError(
            "GITHUB_TOKEN no configurado. "
            "Agrégalo en el archivo .env"
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": settings.ai_model,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }

    logger.info("openai_vision_llamada", model=settings.ai_model)

    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{settings.ai_base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()

    result = response.json()
    text_response = result["choices"][0]["message"]["content"]

    logger.info(
        "openai_vision_respuesta",
        tokens_input=result.get("usage", {}).get("prompt_tokens"),
        tokens_output=result.get("usage", {}).get("completion_tokens"),
    )

    # Limpiar respuesta (a veces viene con ```json ... ```)
    text_clean = text_response.strip()
    if text_clean.startswith("```"):
        text_clean = text_clean.split("\n", 1)[1]
        text_clean = text_clean.rsplit("```", 1)[0]

    return json.loads(text_clean)


def _parse_response(data: dict) -> OcrResult:
    """Parsea la respuesta del modelo a nuestro schema."""
    extracted = data.get("extracted_data", {})
    confidence = data.get("confidence", {})
    needs_review = data.get("needs_review", [])
    notas = data.get("notas", "")

    # Normalizar EPS
    if "eps_detectada" in extracted and extracted["eps_detectada"]:
        extracted["eps_detectada"] = _normalize_eps(extracted["eps_detectada"])

    # Construir OcrExtractedData (ignora campos que el modelo no reconoció)
    valid_fields = OcrExtractedData.model_fields.keys()
    clean_data = {k: v for k, v in extracted.items() if k in valid_fields and v is not None}

    ocr_data = OcrExtractedData(**clean_data)

    if needs_review:
        logger.info("campos_revision_humana", campos=needs_review)

    if notas:
        logger.info("notas_ai", notas=notas)

    return OcrResult(
        status="processed",
        extracted_data=ocr_data,
        confidence=confidence,
    )


def _normalize_eps(eps: str) -> str:
    """Normaliza el nombre de la EPS."""
    mapping = {
        "SURAMERICANA": "SURA",
        "EPS SURA": "SURA",
        "EPS SANITAS": "SANITAS",
        "NUEVA EPS": "NUEVA_EPS",
        "SALUD TOTAL": "SALUD_TOTAL",
        "MUTUAL SER": "MUTUAL_SER",
    }
    upper = eps.upper().strip()
    return mapping.get(upper, upper)
