"""Tests de schemas — valida que los modelos Pydantic parsean correctamente."""

import json
from pathlib import Path

import pytest

from app.schemas import (
    AcceptedResponse,
    AutomationJobRequest,
    CompletedCallback,
    FailedCallback,
    JobType,
    OcrJobResult,
    ProgressCallback,
    ProgressEvent,
    RadicacionJobResult,
)


# Ruta a los JSONs oficiales del reto
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "pluggin" / "RetoIncapacidadesColombia" / "RetoIncapacidadesColombia" / "json"


class TestOcrJobRequest:
    """Tests del payload OCR + ADRES + RETHUS."""

    def test_parse_ocr_request(self):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.request.json").read_text())
        req = AutomationJobRequest(**raw)

        assert req.job.uuid == "job-ocr-123"
        assert req.job.type == JobType.OCR_ADRES_RETHUS
        assert req.empresa.razon_social == "EMPRESA SAS"
        assert req.trabajador.numero_documento == "123456789"
        assert req.trabajador.eps_actual == "SANITAS"
        assert req.caso_preliminar is not None
        assert req.caso_preliminar.uuid == "inc-456"
        assert len(req.adjuntos) == 1
        assert req.adjuntos[0].size_kb == 850

    def test_parse_ocr_response(self):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.response.success.json").read_text())
        cb = CompletedCallback(
            job_uuid=raw["job_uuid"],
            incapacidad_uuid=raw["incapacidad_uuid"],
            event=raw["event"],
            status=raw["status"],
            result=OcrJobResult(**raw["result"]),
        )

        assert cb.job_uuid == "job-ocr-123"
        assert cb.result.ocr.status == "processed"
        assert cb.result.ocr.extracted_data.eps_detectada == "SANITAS"
        assert cb.result.adres.eps_encontrada == "SANITAS"
        assert cb.result.rethus.medico.rethus == "VALIDADO"
        assert cb.result.ocr.confidence["eps_detectada"] == 0.91


class TestRadicacionJobRequest:
    """Tests del payload de radicación EPS."""

    def test_parse_radicacion_request(self):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.request.json").read_text())
        req = AutomationJobRequest(**raw)

        assert req.job.uuid == "job-rpa-999"
        assert req.job.type == JobType.EPS_RADICACION
        assert req.incapacidad is not None
        assert req.incapacidad.numero_incapacidad == "INC-12345"
        assert req.incapacidad.dias == 5
        assert req.medico is not None
        assert req.medico.registro_medico == "123456"
        assert req.radicacion is not None
        assert req.radicacion.adapter_key == "sanitas"
        assert req.radicacion.max_file_size_kb == 12288
        assert len(req.adjuntos) == 2

    def test_parse_radicacion_success(self):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.response.success.json").read_text())

        assert raw["status"] == "success"
        assert raw["result"]["radicacion"]["numero_radicado"] == "RAD-123456"

    def test_parse_radicacion_error(self):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.response.error.json").read_text())
        cb = FailedCallback(
            job_uuid=raw["job_uuid"],
            incapacidad_uuid=raw["incapacidad_uuid"],
            event=raw["event"],
            status=raw["status"],
            error=raw["error"],
            evidencias=raw.get("evidencias", []),
        )

        assert cb.error.code == "PORTAL_TIMEOUT"
        assert cb.error.step == "upload_document"
        assert len(cb.evidencias) == 1


class TestProgressCallback:
    """Tests de callbacks de progreso."""

    def test_progress_events(self):
        for event in ProgressEvent:
            cb = ProgressCallback(
                job_uuid="test-123",
                incapacidad_uuid="inc-456",
                event=event,
                status="running",
                progress=50,
                message=f"Evento: {event.value}",
            )
            data = cb.model_dump(mode="json")
            assert data["event"] == event.value

    def test_accepted_response(self):
        resp = AcceptedResponse(job_uuid="job-123")
        assert resp.status == "accepted"
        assert resp.job_uuid == "job-123"
