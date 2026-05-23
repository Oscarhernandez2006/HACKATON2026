"""Servicio de validación RETHUS — verifica registro del profesional médico.

RETHUS (Registro Único Nacional del Talento Humano en Salud) permite verificar
que el médico que expidió la incapacidad está registrado y habilitado.

La consulta se hace al portal del Ministerio de Salud.
"""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logger import get_logger
from app.schemas import RethusResult, RethusValidatedMedico

logger = get_logger(__name__)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _query_rethus(registro_medico: str) -> dict | None:
    """Consulta RETHUS por número de registro médico / tarjeta profesional."""
    settings = get_settings()
    base_url = settings.rethus_base_url

    url = f"{base_url}/habilitacion/consulta"

    params = {
        "registroProfesional": registro_medico,
    }

    logger.info("rethus_consulta", registro=registro_medico)

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)

        if response.status_code == 404:
            logger.warning("rethus_no_encontrado", registro=registro_medico)
            return None

        response.raise_for_status()
        return response.json()


def _query_rethus_by_document(tipo_doc: str, numero_doc: str) -> dict | None:
    """Consulta RETHUS por tipo y número de documento del médico."""
    settings = get_settings()
    base_url = settings.rethus_base_url

    url = f"{base_url}/habilitacion/consulta"

    params = {
        "tipoDocumento": tipo_doc,
        "numeroDocumento": numero_doc,
    }

    logger.info(
        "rethus_consulta_documento",
        tipo_doc=tipo_doc,
        doc_parcial=f"***{numero_doc[-4:]}" if len(numero_doc) >= 4 else "***",
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()


def validate_rethus(
    registro_medico: str | None = None,
    medico_nombre: str | None = None,
    tipo_documento: str | None = None,
    numero_documento: str | None = None,
) -> RethusResult:
    """Valida un profesional médico en RETHUS.

    Intenta primero por registro médico, luego por documento.

    Args:
        registro_medico: Número de registro o tarjeta profesional.
        medico_nombre: Nombre del médico (del OCR, para cruzar).
        tipo_documento: Tipo de documento del médico (si se tiene).
        numero_documento: Número de documento del médico (si se tiene).

    Returns:
        RethusResult con el estado de validación.
    """
    data = None

    # Intentar por registro médico primero
    if registro_medico:
        try:
            data = _query_rethus(registro_medico)
        except Exception:
            logger.exception("rethus_error_consulta_registro")

    # Fallback por documento
    if data is None and tipo_documento and numero_documento:
        try:
            data = _query_rethus_by_document(tipo_documento, numero_documento)
        except Exception:
            logger.exception("rethus_error_consulta_documento")

    if data is None:
        logger.warning("rethus_medico_no_encontrado")
        return RethusResult(
            status="not_found",
            medico=RethusValidatedMedico(
                nombre=medico_nombre or "DESCONOCIDO",
                registro_medico=registro_medico or "N/A",
                rethus="NO_ENCONTRADO",
            ) if medico_nombre or registro_medico else None,
        )

    # Parsear respuesta
    nombre = _extract_nombre(data) or medico_nombre or "DESCONOCIDO"
    registro = _extract_registro(data) or registro_medico or "N/A"
    especialidad = _extract_especialidad(data)
    estado = _extract_estado(data)

    is_valid = estado in ("ACTIVO", "HABILITADO", "VIGENTE")

    logger.info(
        "rethus_validacion_completa",
        nombre=nombre,
        registro=registro,
        especialidad=especialidad,
        estado=estado,
        valido=is_valid,
    )

    return RethusResult(
        status="success" if is_valid else "invalid",
        medico=RethusValidatedMedico(
            nombre=nombre,
            registro_medico=registro,
            especialidad=especialidad,
            rethus="VALIDADO" if is_valid else "NO_VALIDADO",
        ),
    )


def _extract_nombre(data: dict) -> str | None:
    """Extrae el nombre del profesional de la respuesta RETHUS."""
    for key in ("nombreCompleto", "nombre", "profesional", "nombreProfesional"):
        if key in data:
            return str(data[key]).strip().upper()

    # Construir desde partes
    nombres = data.get("nombres", "")
    apellidos = data.get("apellidos", "")
    if nombres or apellidos:
        return f"{nombres} {apellidos}".strip().upper()

    return None


def _extract_registro(data: dict) -> str | None:
    """Extrae el número de registro profesional."""
    for key in ("registroProfesional", "registro", "tarjetaProfesional", "numeroRegistro"):
        if key in data:
            return str(data[key]).strip()
    return None


def _extract_especialidad(data: dict) -> str | None:
    """Extrae la especialidad del profesional."""
    for key in ("especialidad", "profesion", "tituloProfesional", "formacion"):
        if key in data:
            return str(data[key]).strip().upper()
    return None


def _extract_estado(data: dict) -> str | None:
    """Extrae el estado de habilitación del profesional."""
    for key in ("estado", "estadoHabilitacion", "estadoRegistro"):
        if key in data:
            return str(data[key]).strip().upper()
    return "ACTIVO"  # Default si no viene explícito
