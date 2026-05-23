"""Extractor estructurado — parsea texto OCR y extrae campos de incapacidad.

Extrae: número de incapacidad, tipo, fechas, diagnóstico, EPS, médico, etc.
Calcula nivel de confianza por campo.
Marca campos con baja confianza para revisión humana.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.logger import get_logger
from app.schemas import OcrExtractedData

logger = get_logger(__name__)

# Umbral de confianza: debajo de esto se marca para revisión humana
CONFIDENCE_THRESHOLD = 0.7

# ── Patrones regex para documentos médicos colombianos ──

_PATTERNS = {
    "numero_incapacidad": [
        r"(?:N[°ºo]?\s*(?:de\s+)?(?:incapacidad|radicado|certificado))\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"(?:incapacidad|certificado)\s*(?:N[°ºo]?)?\s*[:\-]?\s*([A-Z0-9\-]{4,})",
        r"(?:RAD|INC|CERT)\s*[\-:]?\s*(\d{4,})",
    ],
    "diagnostico_codigo": [
        r"(?:CIE[\-\s]?10|C[oó]digo\s+diagn[oó]stico|Dx)\s*[:\-]?\s*([A-Z]\d{2,4}(?:\.\d+)?)",
        r"\b([A-Z]\d{2}(?:\.\d{1,2})?)\b",
    ],
    "eps_detectada": [
        r"(?:EPS|Entidad|Aseguradora)\s*[:\-]?\s*(SANITAS|SURA|COMPENSAR|NUEVA\s*EPS|SALUD\s*TOTAL|COOSALUD|FAMISANAR|MUTUAL\s*SER)",
        r"\b(SANITAS|SURA|COMPENSAR|NUEVA\s*EPS|SALUD\s*TOTAL|COOSALUD|FAMISANAR|MUTUAL\s*SER)\b",
    ],
    "medico_nombre": [
        r"(?:M[eé]dico|Doctor|Dra?\.?|Profesional)\s*(?:tratante)?\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,40})",
        r"(?:Firma|Atendido\s+por)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,40})",
    ],
    "registro_medico": [
        r"(?:Registro\s+m[eé]dico|Reg\.?\s*Med\.?|R\.?M\.?|Tarjeta\s+profesional)\s*[:\-]?\s*(\d{4,10})",
        r"(?:TP|T\.P\.)\s*[:\-]?\s*(\d{4,10})",
    ],
    "ips": [
        r"(?:IPS|Instituci[oó]n|Centro\s+m[eé]dico|Cl[ií]nica|Hospital)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s\.]{3,50})",
    ],
}

_DATE_PATTERNS = [
    # DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})",
    # YYYY-MM-DD
    r"(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})",
]

_DATE_LABELS = {
    "fecha_expedicion": [
        r"(?:fecha\s+(?:de\s+)?expedici[oó]n|expedido\s+el|fecha\s+documento)",
    ],
    "fecha_atencion": [
        r"(?:fecha\s+(?:de\s+)?atenci[oó]n|fecha\s+consulta|atendido\s+el)",
    ],
    "fecha_inicio": [
        r"(?:fecha\s+(?:de\s+)?inicio|inicia?\s+el|desde\s+el|a\s+partir\s+del)",
    ],
    "fecha_fin": [
        r"(?:fecha\s+(?:de\s+)?(?:fin|terminaci[oó]n|finalizaci[oó]n)|hasta\s+el|termina\s+el)",
    ],
}

_TIPO_PATTERNS = [
    (r"enfermedad\s+general", "ENFERMEDAD_GENERAL"),
    (r"accidente\s+(?:de\s+)?trabajo|AT\b", "ACCIDENTE_TRABAJO"),
    (r"maternidad|licencia\s+(?:de\s+)?maternidad", "LICENCIA_MATERNIDAD"),
    (r"paternidad|licencia\s+(?:de\s+)?paternidad", "LICENCIA_PATERNIDAD"),
    (r"enfermedad\s+laboral|EL\b", "ENFERMEDAD_LABORAL"),
]

_DIAS_PATTERNS = [
    r"(?:d[ií]as?\s+(?:de\s+)?incapacidad|total\s+d[ií]as|d[ií]as\s+otorgados)\s*[:\-]?\s*(\d{1,3})",
    r"(\d{1,3})\s*d[ií]as?\s+(?:de\s+)?incapacidad",
]

_PRORROGA_PATTERNS = [
    r"(?:pr[oó]rroga|extensi[oó]n|continuaci[oó]n|prolongaci[oó]n)",
]


@dataclass
class ExtractionResult:
    """Resultado de la extracción con datos y confianzas."""
    data: OcrExtractedData
    confidence: dict[str, float] = field(default_factory=dict)
    needs_review: list[str] = field(default_factory=list)


def extract_structured_data(raw_text: str) -> ExtractionResult:
    """Extrae datos estructurados del texto OCR crudo.

    Returns:
        ExtractionResult con datos, confianzas y campos que necesitan revisión.
    """
    text_upper = raw_text.upper()
    text_clean = raw_text.strip()

    data = {}
    confidence = {}

    # ── Campos de texto ──
    for field_name, patterns in _PATTERNS.items():
        value, conf = _find_best_match(text_clean, patterns)
        if value:
            data[field_name] = _clean_value(value)
            confidence[field_name] = conf
        else:
            confidence[field_name] = 0.0

    # ── Fechas ──
    for date_field, label_patterns in _DATE_LABELS.items():
        date_val, conf = _extract_date_near_label(text_clean, label_patterns)
        if date_val:
            data[date_field] = date_val
            confidence[date_field] = conf

    # ── Tipo de incapacidad ──
    for pattern, tipo in _TIPO_PATTERNS:
        if re.search(pattern, text_clean, re.IGNORECASE):
            data["tipo"] = tipo
            confidence["tipo"] = 0.9
            break

    if "tipo" not in data:
        data["tipo"] = "ENFERMEDAD_GENERAL"
        confidence["tipo"] = 0.5

    # ── Origen ──
    data["origen"] = "COMUN" if data.get("tipo") == "ENFERMEDAD_GENERAL" else "LABORAL"

    # ── Días de incapacidad ──
    for pattern in _DIAS_PATTERNS:
        match = re.search(pattern, text_clean, re.IGNORECASE)
        if match:
            data["dias"] = int(match.group(1))
            confidence["dias"] = 0.85
            break

    # ── Prórroga ──
    is_prorroga = any(
        re.search(p, text_clean, re.IGNORECASE) for p in _PRORROGA_PATTERNS
    )
    data["es_prorroga"] = is_prorroga

    # ── Normalizar EPS ──
    if "eps_detectada" in data:
        data["eps_detectada"] = _normalize_eps(data["eps_detectada"])

    # ── Determinar campos que necesitan revisión humana ──
    needs_review = [
        f for f, c in confidence.items()
        if c < CONFIDENCE_THRESHOLD and f in data
    ]

    extracted = OcrExtractedData(**data)

    logger.info(
        "extraccion_completada",
        campos_extraidos=len(data),
        campos_revision=len(needs_review),
        needs_review=needs_review,
    )

    return ExtractionResult(
        data=extracted,
        confidence=confidence,
        needs_review=needs_review,
    )


def _find_best_match(text: str, patterns: list[str]) -> tuple[str | None, float]:
    """Busca la mejor coincidencia entre varios patrones.

    Retorna (valor, confianza). El primer patrón que coincida tiene mayor confianza.
    """
    for i, pattern in enumerate(patterns):
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            # Más confianza si matchea el patrón más específico (primero)
            conf = max(0.5, 1.0 - (i * 0.15))
            return match.group(1).strip(), conf
    return None, 0.0


def _extract_date_near_label(
    text: str, label_patterns: list[str]
) -> tuple[str | None, float]:
    """Busca una fecha cerca de una etiqueta de contexto."""
    for label_pattern in label_patterns:
        # Buscar etiqueta + fecha en la misma línea o cercana
        combined = label_pattern + r"[:\s\-]*" + _DATE_PATTERNS[0]
        match = re.search(combined, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            date_str = _parse_date_groups(groups[-3:])
            if date_str:
                return date_str, 0.9

    # Fallback: buscar cualquier fecha en el texto
    for pattern in _DATE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            date_str = _parse_date_groups(matches[0])
            if date_str:
                return date_str, 0.5

    return None, 0.0


def _parse_date_groups(groups: tuple) -> str | None:
    """Convierte grupos capturados en fecha YYYY-MM-DD."""
    try:
        a, b, c = [int(g) for g in groups]
        if a > 1900:  # YYYY-MM-DD
            d = date(a, b, c)
        else:  # DD/MM/YYYY
            d = date(c, b, a)
        return d.isoformat()
    except (ValueError, TypeError):
        return None


def _clean_value(value: str) -> str:
    """Limpia un valor extraído."""
    return re.sub(r"\s+", " ", value).strip()


def _normalize_eps(eps: str) -> str:
    """Normaliza nombre de EPS a código estándar."""
    eps_upper = eps.upper().strip()
    mapping = {
        "NUEVA EPS": "NUEVA_EPS",
        "SALUD TOTAL": "SALUD_TOTAL",
        "MUTUAL SER": "MUTUAL_SER",
        "EPS SURA": "SURA",
        "EPS SANITAS": "SANITAS",
    }
    return mapping.get(eps_upper, eps_upper)
