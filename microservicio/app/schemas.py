"""Schemas Pydantic — contratos de integración con Laravel.

Alineados 1:1 con los JSONs oficiales del reto:
  - job_ocr_adres_rethus.request.json
  - job_radicacion.request.json
  - Responses y callbacks
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ╔══════════════════════════════════════════════════════════════════╗
# ║  ENUMS                                                         ║
# ╚══════════════════════════════════════════════════════════════════╝

class JobType(str, Enum):
    OCR_ADRES_RETHUS = "ocr_adres_rethus"
    EPS_RADICACION = "eps_radicacion"


class JobStatus(str, Enum):
    RECEIVED = "received"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ProgressEvent(str, Enum):
    JOB_RECEIVED = "job_received"
    OCR_STARTED = "ocr_started"
    OCR_FINISHED = "ocr_finished"
    ADRES_STARTED = "adres_started"
    ADRES_FINISHED = "adres_finished"
    RETHUS_STARTED = "rethus_started"
    RETHUS_FINISHED = "rethus_finished"
    RPA_STARTED = "rpa_started"
    RPA_FINISHED = "rpa_finished"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"


class TipoAdjunto(str, Enum):
    CERTIFICADO_INCAPACIDAD = "CERTIFICADO_INCAPACIDAD"
    HISTORIA_CLINICA_RESUMEN = "HISTORIA_CLINICA_RESUMEN"


# ╔══════════════════════════════════════════════════════════════════╗
# ║  REQUEST — Componentes compartidos                              ║
# ╚══════════════════════════════════════════════════════════════════╝

class JobInfo(BaseModel):
    uuid: str
    type: JobType
    callback_url: str


class Empresa(BaseModel):
    id: int
    tipo_identificacion: str
    numero_identificacion: str
    razon_social: str
    correo_contacto: str | None = None
    telefono_contacto: str | None = None


class Trabajador(BaseModel):
    id: int
    tipo_documento: str
    numero_documento: str
    nombres: str
    apellidos: str
    eps_actual: str
    tipo_cotizante: str | None = None
    ibc: float | None = None


class Adjunto(BaseModel):
    tipo: TipoAdjunto
    archivo_id: int
    nombre_original: str
    mime_type: str
    size_kb: int
    url_temporal: str


# ╔══════════════════════════════════════════════════════════════════╗
# ║  REQUEST — Job OCR + ADRES + RETHUS                            ║
# ╚══════════════════════════════════════════════════════════════════╝

class CasoPreliminar(BaseModel):
    id: int
    uuid: str
    estado_actual: str


class OcrJobRequest(BaseModel):
    """Payload que Laravel envía para job tipo ocr_adres_rethus."""
    job: JobInfo
    empresa: Empresa
    trabajador: Trabajador
    caso_preliminar: CasoPreliminar
    adjuntos: list[Adjunto]


# ╔══════════════════════════════════════════════════════════════════╗
# ║  REQUEST — Job Radicación EPS                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

class Incapacidad(BaseModel):
    id: int
    uuid: str
    numero_incapacidad: str
    tipo: str
    origen: str
    fecha_expedicion: date
    fecha_atencion: date
    fecha_inicio: date
    fecha_fin: date
    dias: int
    diagnostico_codigo: str
    es_prorroga: bool = False
    estado_actual: str


class Medico(BaseModel):
    id: int
    tipo_documento: str
    numero_documento: str
    nombre: str
    especialidad: str
    registro_medico: str
    rethus: str
    ips: str


class RadicacionConfig(BaseModel):
    eps_code: str
    portal_url: str
    adapter_key: str
    max_file_size_kb: int
    credencial_ref: str


class RadicacionJobRequest(BaseModel):
    """Payload que Laravel envía para job tipo eps_radicacion."""
    job: JobInfo
    empresa: Empresa
    trabajador: Trabajador
    incapacidad: Incapacidad
    medico: Medico
    radicacion: RadicacionConfig
    adjuntos: list[Adjunto]


# ╔══════════════════════════════════════════════════════════════════╗
# ║  REQUEST — Unificado (el endpoint recibe uno u otro)           ║
# ╚══════════════════════════════════════════════════════════════════╝

class AutomationJobRequest(BaseModel):
    """Payload genérico que llega a POST /automation/jobs.
    Contiene los campos comunes; los específicos son opcionales
    y se validan según job.type.
    """
    job: JobInfo
    empresa: Empresa
    trabajador: Trabajador

    # Solo para ocr_adres_rethus
    caso_preliminar: CasoPreliminar | None = None
    # Solo para eps_radicacion
    incapacidad: Incapacidad | None = None
    medico: Medico | None = None
    radicacion: RadicacionConfig | None = None

    adjuntos: list[Adjunto]


# ╔══════════════════════════════════════════════════════════════════╗
# ║  RESPONSE — Resultado OCR                                     ║
# ╚══════════════════════════════════════════════════════════════════╝

class OcrExtractedData(BaseModel):
    numero_incapacidad: str | None = None
    tipo: str | None = None
    origen: str | None = None
    fecha_expedicion: str | None = None
    fecha_atencion: str | None = None
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    dias: int | None = None
    diagnostico_codigo: str | None = None
    eps_detectada: str | None = None
    medico_nombre: str | None = None
    registro_medico: str | None = None
    ips: str | None = None
    es_prorroga: bool | None = None


class OcrResult(BaseModel):
    status: str  # "processed"
    extracted_data: OcrExtractedData
    confidence: dict[str, float] = Field(default_factory=dict)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  RESPONSE — Resultado ADRES                                   ║
# ╚══════════════════════════════════════════════════════════════════╝

class AdresResult(BaseModel):
    status: str  # "success" | "not_found" | "error"
    fecha_validacion: str | None = None
    eps_encontrada: str | None = None
    estado_afiliacion: str | None = None
    coincide_con_eps_laravel: bool | None = None


# ╔══════════════════════════════════════════════════════════════════╗
# ║  RESPONSE — Resultado RETHUS                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

class RethusValidatedMedico(BaseModel):
    nombre: str
    registro_medico: str
    especialidad: str | None = None
    rethus: str  # "VALIDADO" | "NO_ENCONTRADO"


class RethusResult(BaseModel):
    status: str
    medico: RethusValidatedMedico | None = None


# ╔══════════════════════════════════════════════════════════════════╗
# ║  RESPONSE — Resultado Radicación                               ║
# ╚══════════════════════════════════════════════════════════════════╝

class Evidencia(BaseModel):
    tipo: str  # "screenshot" | "comprobante"
    url: str


class RadicacionResult(BaseModel):
    status: str  # "success" | "failed"
    numero_radicado: str | None = None
    mensaje: str | None = None
    evidencias: list[Evidencia] = Field(default_factory=list)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  CALLBACKS — Progreso y resultado final                        ║
# ╚══════════════════════════════════════════════════════════════════╝

class ProgressCallback(BaseModel):
    """Callback de progreso que se envía a Laravel durante el procesamiento."""
    job_uuid: str
    incapacidad_uuid: str
    event: ProgressEvent
    status: JobStatus
    progress: int = 0  # 0-100
    message: str = ""


class OcrJobResult(BaseModel):
    """Resultado final del job ocr_adres_rethus."""
    ocr: OcrResult
    adres: AdresResult
    rethus: RethusResult


class RadicacionJobResult(BaseModel):
    """Resultado final del job eps_radicacion."""
    radicacion: RadicacionResult


class CompletedCallback(BaseModel):
    """Callback final exitoso hacia Laravel."""
    job_uuid: str
    incapacidad_uuid: str
    event: str = ProgressEvent.JOB_COMPLETED
    status: str = JobStatus.SUCCESS
    result: OcrJobResult | RadicacionJobResult


class ErrorDetail(BaseModel):
    code: str
    message: str
    step: str | None = None


class FailedCallback(BaseModel):
    """Callback de error hacia Laravel."""
    job_uuid: str
    incapacidad_uuid: str
    event: str = ProgressEvent.JOB_FAILED
    status: str = JobStatus.FAILED
    error: ErrorDetail
    evidencias: list[Evidencia] = Field(default_factory=list)


# ╔══════════════════════════════════════════════════════════════════╗
# ║  RESPONSE — Respuesta HTTP 202 del endpoint                   ║
# ╚══════════════════════════════════════════════════════════════════╝

class AcceptedResponse(BaseModel):
    """Respuesta inmediata del endpoint POST /automation/jobs."""
    job_uuid: str
    status: str = "accepted"
    message: str = "Job recibido y encolado para procesamiento"
