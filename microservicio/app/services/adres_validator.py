"""Servicio de validación ADRES — consulta afiliación del trabajador.

ADRES (Administradora de los Recursos del Sistema General de Seguridad Social en Salud)
expone una consulta pública de afiliados por documento y fecha.

Valida:
- Que el trabajador esté afiliado
- Que la EPS reportada coincida con la del sistema Laravel
- Estado de afiliación (ACTIVO, SUSPENDIDO, etc.)
"""

from __future__ import annotations

from datetime import date

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.logger import get_logger
from app.schemas import AdresResult

logger = get_logger(__name__)

# Mapeo de tipos de documento al código ADRES
_TIPO_DOC_ADRES = {
    "CC": "CC",
    "CE": "CE",
    "TI": "TI",
    "PA": "PA",
    "RC": "RC",
    "NIT": "NI",
    "CD": "CD",  # Carnet diplomático
    "SC": "SC",  # Salvoconducto
    "PE": "PE",  # Permiso especial de permanencia
    "PT": "PT",  # Permiso por protección temporal
}


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
def _query_adres(tipo_doc: str, numero_doc: str, fecha: str) -> dict | None:
    """Consulta la API pública de ADRES.

    La consulta se hace al endpoint de BDUA (Base de Datos Única de Afiliados).
    """
    settings = get_settings()
    base_url = settings.adres_base_url

    tipo_adres = _TIPO_DOC_ADRES.get(tipo_doc.upper(), tipo_doc.upper())

    # Endpoint público de consulta de afiliados ADRES
    url = f"{base_url}/bdua/consulta"

    params = {
        "tipoDocumento": tipo_adres,
        "numeroDocumento": numero_doc,
        "fechaConsulta": fecha,
    }

    logger.info(
        "adres_consulta",
        tipo_doc=tipo_adres,
        # Solo últimos 4 dígitos por seguridad
        doc_parcial=f"***{numero_doc[-4:]}",
        fecha=fecha,
    )

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, params=params)

        if response.status_code == 404:
            logger.warning("adres_no_encontrado")
            return None

        response.raise_for_status()
        return response.json()


def validate_adres(
    tipo_documento: str,
    numero_documento: str,
    fecha_inicio: str | None,
    eps_laravel: str,
) -> AdresResult:
    """Valida la afiliación del trabajador en ADRES.

    Args:
        tipo_documento: Tipo de documento (CC, CE, TI, etc.)
        numero_documento: Número de documento del trabajador.
        fecha_inicio: Fecha de inicio de la incapacidad (YYYY-MM-DD).
        eps_laravel: EPS que tiene registrada Laravel para comparar.

    Returns:
        AdresResult con el estado de la validación.
    """
    if not fecha_inicio:
        logger.warning("adres_sin_fecha_inicio, usando fecha actual")
        fecha_inicio = date.today().isoformat()

    try:
        data = _query_adres(tipo_documento, numero_documento, fecha_inicio)
    except Exception as exc:
        logger.exception("adres_error_consulta")
        return AdresResult(
            status="error",
            fecha_validacion=fecha_inicio,
        )

    if data is None:
        return AdresResult(
            status="not_found",
            fecha_validacion=fecha_inicio,
        )

    # Parsear respuesta ADRES
    # La estructura varía según el endpoint, pero típicamente:
    eps_encontrada = _extract_eps(data)
    estado = _extract_estado(data)

    # Normalizar para comparar
    eps_norm = _normalize_eps_name(eps_encontrada) if eps_encontrada else None
    laravel_norm = _normalize_eps_name(eps_laravel)
    coincide = eps_norm == laravel_norm if eps_norm else None

    logger.info(
        "adres_validacion_completa",
        eps_encontrada=eps_encontrada,
        estado=estado,
        coincide=coincide,
    )

    return AdresResult(
        status="success",
        fecha_validacion=fecha_inicio,
        eps_encontrada=eps_encontrada,
        estado_afiliacion=estado,
        coincide_con_eps_laravel=coincide,
    )


def _extract_eps(data: dict) -> str | None:
    """Extrae el nombre de la EPS de la respuesta ADRES."""
    # Campos comunes en respuestas ADRES
    for key in ("nombreEPS", "eps", "entidad", "eapb", "nombreEntidad"):
        if key in data:
            return str(data[key]).strip()

    # Buscar en datos anidados
    if "afiliacion" in data and isinstance(data["afiliacion"], dict):
        for key in ("eps", "nombreEPS", "entidad"):
            if key in data["afiliacion"]:
                return str(data["afiliacion"][key]).strip()

    return None


def _extract_estado(data: dict) -> str | None:
    """Extrae el estado de afiliación de la respuesta ADRES."""
    for key in ("estadoAfiliacion", "estado", "estadoAfiliado"):
        if key in data:
            return str(data[key]).strip().upper()

    if "afiliacion" in data and isinstance(data["afiliacion"], dict):
        for key in ("estado", "estadoAfiliacion"):
            if key in data["afiliacion"]:
                return str(data["afiliacion"][key]).strip().upper()

    return None


def _normalize_eps_name(name: str) -> str:
    """Normaliza el nombre de EPS para comparación."""
    import re

    normalized = name.upper().strip()
    # Remover "EPS", "S.A.", "S.A.S", etc.
    normalized = re.sub(r"\b(EPS|S\.?A\.?S?\.?|E\.?P\.?S\.?)\b", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # Mapeo de variaciones conocidas
    aliases = {
        "SURAMERICANA": "SURA",
        "NUEVA": "NUEVA_EPS",
        "SALUD TOTAL": "SALUD_TOTAL",
        "MUTUAL SER": "MUTUAL_SER",
        "ENTIDAD PROMOTORA DE SALUD SANITAS": "SANITAS",
        "ENTIDAD PROMOTORA DE SALUD SURA": "SURA",
        "COOMEVA": "COOMEVA",
    }

    for alias, canonical in aliases.items():
        if alias in normalized:
            return canonical

    return normalized
