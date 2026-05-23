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
        r"(?:N[°ºo]|Nº)\s*\.?\s*(\d{3,})",
        r"(?:incapacidad|radicado|certificado)\s*(?:N[°ºo]?)?\s*[:\-.]?\s*(\d{3,})",
        r"No\.\s*(\d{4,})",
        r"(?:RAD|INC|CERT)\s*[\-:]?\s*(\d{4,})",
    ],
    "diagnostico_codigo": [
        r"(?:CIE[\-\s]?10|C[oó]digo\s+[Dd]iagn[oó]stico\s+[Pp]rincipal|Dx)\s*[:\-]?\s*([A-Z]\d{2,4}(?:\.\d+)?)",
        r"(?:incapacidad|diagnostico)[:\s]*([A-Z]\d{2,4})\b",
        r"\b([A-Z]\d{3})\s+[\-–]\s+[A-ZÁÉÍÓÚÑ]",
        r"\b([A-Z]\d{3})\s+[A-ZÁÉÍÓÚÑ]{2,}",
    ],
    "diagnostico_descripcion": [
        r"[A-Z]\d{3}\s*[\-–]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s,]{5,60})",
    ],
    "eps_detectada": [
        r"(?:EPS|Entidad|Aseguradora|Administradora)\s*[:\-]?\s*(?:EPS\d*\s+)?(?:EPS\s+Y\s+MEDICINA\s+PREPAGADA\s+)?(SANITAS|SURA(?:MERICANA)?|COMPENSAR|NUEVA\s*EPS|SALUD\s*TOTAL|COOSALUD|FAMISANAR|MUTUAL\s*SER)",
        r"(?:EPS\s+Y\s+MEDICINA\s+PREPAGADA\s+)(SURAMERICANA)",
        r"\b(SANITAS|COMPENSAR|COOSALUD|FAMISANAR)\b",
        r"\b(SALUD\s+TOTAL)\s+EPS\b",
        r"\b(SURAMERICANA)\b",
        r"\b(NUEVA\s+EPS)\b",
        r"\b(MUTUAL\s+SER)\b",
    ],
    "medico_nombre": [
        r"(?:DR\.?|DRA\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]{5,40}?)(?:\s*[\-–]\s*|\s+CC\b|\s+M[eé]dico)",
        r"M[eé]dico\s*[:\-]?\s*\n?\s*(?:\d+\s*\n?\s*)?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,40})",
        r"(?:Firma|Atendido\s+por)\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,40})",
        r"T\.\s*Profesional\s*\n?\s*\d+\s*\n?\s*(?:Especialidad\s*\n?\s*[A-Z\s]+\s*\n?\s*)?.*?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{5,30})",
    ],
    "registro_medico": [
        r"(?:Registro\s+m[eé]dico|Reg\.?\s*Med\.?|R\.?M\.?|T\.?\s*Profesional|TP|T\.P\.)\s*[:\-]?\s*(\d{4,15})",
        r"RM\.\s*(\d{4,15})",
        r"CC\s+(\d{6,15})\s+[\-–]\s+RM",
    ],
    "ips": [
        r"(CL[IÍ]NICA\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,40})",
        r"(HOSPITAL\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,40})",
        r"(COOPERATIVA\s+[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{2,40}(?:\s+IPS)?)",
        r"Centro\s+m[eé]dico\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]{2,40})",
    ],
}

_DATE_PATTERNS = [
    # DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY
    r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})",
    # YYYY-MM-DD
    r"(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})",
]

# Meses en español para formatos como "21/abril/2026"
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

_DATE_LABELS = {
    "fecha_inicio": [
        r"(?:fecha\s+(?:de\s+)?inicio|[Dd]esde|[Ii]nicia?\s+el|[Aa]\s+partir\s+del|[Ff]echa\s+[Ii]nicial)",
    ],
    "fecha_fin": [
        r"(?:fecha\s+(?:de\s+)?(?:fin|final|terminaci[oó]n|finalizaci[oó]n)|[Hh]asta|[Tt]ermina\s+el|[Ff]echa\s+[Ff]inal)",
    ],
    "fecha_expedicion": [
        r"(?:fecha\s+(?:de\s+)?expedici[oó]n|[Ee]xpedido\s+el|[Ff]echa\s+[Dd]ocumento|[Ii]mpreso|[Ff]echa\s+[Aa]ctual)",
    ],
    "fecha_atencion": [
        r"(?:fecha\s+(?:de\s+)?atenci[oó]n|[Ff]echa\s+consulta|[Aa]tendido\s+el)",
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
        # Buscar etiqueta seguida de fecha con mes en español (21/abril/2026)
        spanish_date = label_pattern + r"[:\s\-]*(\d{1,2})[/\-]([a-záéíóú]+)[/\-](\d{4})"
        match = re.search(spanish_date, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            day, month_name, year = groups[-3], groups[-2].lower(), groups[-1]
            if month_name in _MESES:
                try:
                    d = date(int(year), _MESES[month_name], int(day))
                    return d.isoformat(), 0.95
                except ValueError:
                    pass

        # Buscar etiqueta + fecha numérica en la misma línea
        combined = label_pattern + r"[:\s\-]*" + _DATE_PATTERNS[0]
        match = re.search(combined, text, re.IGNORECASE)
        if match:
            groups = match.groups()
            date_str = _parse_date_groups(groups[-3:])
            if date_str:
                return date_str, 0.9

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
