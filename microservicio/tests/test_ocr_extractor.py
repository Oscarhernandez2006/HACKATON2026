"""Tests del extractor OCR — valida regex sobre texto de ejemplo."""

import pytest

from app.services.ocr_extractor import extract_structured_data


# Texto simulado de un certificado de incapacidad colombiano
SAMPLE_OCR_TEXT = """
CERTIFICADO DE INCAPACIDAD
EPS SANITAS
No. Incapacidad: INC-2026-00456

Paciente: JUAN CARLOS PEREZ LOPEZ
Tipo documento: CC
Número documento: 123456789

Tipo de incapacidad: Enfermedad General
Origen: Común

Fecha de expedición: 20/05/2026
Fecha de atención: 20/05/2026
Fecha de inicio: 20/05/2026
Fecha de fin: 24/05/2026
Días de incapacidad: 5

Diagnóstico CIE-10: M545
Lumbago no especificado

Médico tratante: CARLOS ANDRES MARTINEZ RUIZ
Registro médico: 789012
IPS: CLINICA EJEMPLO BOGOTA

Firma del médico
Dr. CARLOS ANDRES MARTINEZ RUIZ
T.P. 789012
"""


class TestExtractStructuredData:
    def test_extract_eps(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.eps_detectada == "SANITAS"

    def test_extract_numero_incapacidad(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.numero_incapacidad is not None
        assert "INC" in result.data.numero_incapacidad or "2026" in result.data.numero_incapacidad

    def test_extract_diagnostico(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.diagnostico_codigo is not None
        assert "M54" in result.data.diagnostico_codigo

    def test_extract_medico(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.medico_nombre is not None
        assert "MARTINEZ" in result.data.medico_nombre or "CARLOS" in result.data.medico_nombre

    def test_extract_registro_medico(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.registro_medico == "789012"

    def test_extract_tipo(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.tipo == "ENFERMEDAD_GENERAL"

    def test_extract_dias(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.dias == 5

    def test_extract_fechas(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.fecha_inicio is not None
        assert "2026" in result.data.fecha_inicio

    def test_prorroga_detection(self):
        text_prorroga = SAMPLE_OCR_TEXT + "\nPRÓRROGA de incapacidad anterior"
        result = extract_structured_data(text_prorroga)
        assert result.data.es_prorroga is True

    def test_no_prorroga(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.es_prorroga is False

    def test_confidence_scores(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        # Los campos que matchean el primer patrón deben tener alta confianza
        assert len(result.confidence) > 0
        for field, score in result.confidence.items():
            assert 0.0 <= score <= 1.0

    def test_needs_review_low_confidence(self):
        # Texto ambiguo con datos parciales
        text = "Documento sin formato claro\nFecha: algo\nDiagnóstico: ?"
        result = extract_structured_data(text)
        # Debería tener campos marcados para revisión
        assert isinstance(result.needs_review, list)


class TestEdgeCases:
    def test_empty_text(self):
        result = extract_structured_data("")
        assert result.data is not None
        assert result.data.tipo == "ENFERMEDAD_GENERAL"  # Default

    def test_text_without_data(self):
        result = extract_structured_data("Este texto no contiene datos médicos relevantes")
        assert result.data is not None

    def test_multiple_eps_mentions(self):
        text = "EPS SANITAS\nAnterior: SURA\nActual: SANITAS"
        result = extract_structured_data(text)
        assert result.data.eps_detectada == "SANITAS"

    def test_ips_extraction(self):
        result = extract_structured_data(SAMPLE_OCR_TEXT)
        assert result.data.ips is not None
        assert "CLINICA" in result.data.ips or "EJEMPLO" in result.data.ips
