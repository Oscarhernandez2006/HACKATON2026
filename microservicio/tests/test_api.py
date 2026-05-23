"""Tests del endpoint API — POST /automation/jobs y GET /health."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "pluggin" / "RetoIncapacidadesColombia" / "RetoIncapacidadesColombia" / "json"

VALID_TOKEN = "dev-token"
HEADERS = {"Authorization": f"Bearer {VALID_TOKEN}"}


class TestHealthCheck:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuth:
    def test_no_token(self):
        resp = client.post("/automation/jobs", json={})
        assert resp.status_code in (401, 403)

    def test_bad_token(self):
        resp = client.post(
            "/automation/jobs",
            json={},
            headers={"Authorization": "Bearer token-malo"},
        )
        assert resp.status_code == 401

    def test_valid_token_bad_payload(self):
        resp = client.post(
            "/automation/jobs",
            json={"invalid": True},
            headers=HEADERS,
        )
        assert resp.status_code == 422


class TestCreateOcrJob:
    @patch("app.main.process_automation_job.delay")
    def test_ocr_job_accepted(self, mock_delay):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.request.json").read_text())
        # Poner callback_url con host permitido
        raw["job"]["callback_url"] = "https://localhost/api/internal/automation/jobs/job-ocr-123/result"

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_uuid"] == "job-ocr-123"
        assert data["status"] == "accepted"
        mock_delay.assert_called_once()

    def test_ocr_job_missing_caso_preliminar(self):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.request.json").read_text())
        raw["job"]["callback_url"] = "https://localhost/result"
        del raw["caso_preliminar"]

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)
        assert resp.status_code == 422

    def test_ocr_job_no_adjuntos(self):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.request.json").read_text())
        raw["job"]["callback_url"] = "https://localhost/result"
        raw["adjuntos"] = []

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)
        assert resp.status_code == 422


class TestCreateRadicacionJob:
    @patch("app.main.process_automation_job.delay")
    def test_radicacion_job_accepted(self, mock_delay):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.request.json").read_text())
        raw["job"]["callback_url"] = "https://localhost/result"

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_uuid"] == "job-rpa-999"
        mock_delay.assert_called_once()

    def test_radicacion_file_too_large(self):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.request.json").read_text())
        raw["job"]["callback_url"] = "https://localhost/result"
        # Poner archivo que excede el límite
        raw["adjuntos"][0]["size_kb"] = 99999

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)
        assert resp.status_code == 422
        assert "excede" in resp.json()["detail"]

    def test_radicacion_missing_medico(self):
        raw = json.loads((FIXTURES_DIR / "job_radicacion.request.json").read_text())
        raw["job"]["callback_url"] = "https://localhost/result"
        del raw["medico"]

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)
        assert resp.status_code == 422


class TestCallbackUrlValidation:
    @patch("app.main.process_automation_job.delay")
    def test_callback_url_blocked(self, mock_delay):
        raw = json.loads((FIXTURES_DIR / "job_ocr_adres_rethus.request.json").read_text())
        raw["job"]["callback_url"] = "https://attacker.com/steal"

        resp = client.post("/automation/jobs", json=raw, headers=HEADERS)
        assert resp.status_code == 400
        assert "allowlist" in resp.json()["detail"]
        mock_delay.assert_not_called()
