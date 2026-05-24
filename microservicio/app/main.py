"""FastAPI app principal — De PDF a Radicado."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.auth import verify_token
from app.config import get_settings
from app.logger import get_logger, setup_logging
from app.schemas import (
    AcceptedResponse,
    AutomationJobRequest,
    JobType,
)
from app.worker import process_automation_job


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown del microservicio."""
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()
    logger.info(
        "microservicio_iniciado",
        env=settings.app_env,
        engine="github-models-gpt-4o-mini",
    )
    yield
    logger.info("microservicio_detenido")


app = FastAPI(
    title="De PDF a Radicado",
    description="Microservicio de automatización para Incapacidades.ai",
    version="1.0.0",
    lifespan=lifespan,
)

_STATIC_DIR = Path(__file__).parent / "static"


# ── Interfaz web ──

@app.get("/")
async def root():
    """Sirve la interfaz gráfica de demostración."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/demo", include_in_schema=False)
@app.get("/demo/dashboard", include_in_schema=False)
async def demo_dashboard():
    """Panel visual unificado que consume todos los endpoints /demo/*."""
    return FileResponse(_STATIC_DIR / "dashboard.html")


# ── Health Check ──

@app.get("/health")
async def health():
    """Health check — no requiere autenticación."""
    return {"status": "ok", "service": "pdf-a-radicado"}


# ── Endpoint principal ──

@app.post(
    "/automation/jobs",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_job(
    request: AutomationJobRequest,
    _token: str = Depends(verify_token),
):
    """Recibe un job de Laravel, lo valida y lo encola.

    Responde HTTP 202 inmediatamente.
    El procesamiento ocurre en segundo plano vía Celery.
    """
    settings = get_settings()
    job = request.job

    # ── Validar callback_url contra allowlist ──
    parsed = urlparse(job.callback_url)
    if parsed.hostname not in settings.allowed_hosts_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"callback_url host '{parsed.hostname}' no está en la allowlist",
        )

    # ── Validaciones según tipo de job ──
    if job.type == JobType.OCR_ADRES_RETHUS:
        if request.caso_preliminar is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="caso_preliminar es requerido para job tipo ocr_adres_rethus",
            )
        if not request.adjuntos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Se requiere al menos un adjunto para OCR",
            )

    elif job.type == JobType.EPS_RADICACION:
        if request.incapacidad is None or request.medico is None or request.radicacion is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="incapacidad, medico y radicacion son requeridos para job tipo eps_radicacion",
            )
        if not request.adjuntos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Se requiere al menos un adjunto para radicación",
            )
        # Validar tamaño de archivos contra límite de la EPS
        max_kb = request.radicacion.max_file_size_kb
        for adj in request.adjuntos:
            if adj.size_kb > max_kb:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Adjunto '{adj.nombre_original}' ({adj.size_kb} KB) "
                        f"excede el límite de {max_kb} KB para {request.radicacion.eps_code}"
                    ),
                )

    # ── Encolar el job en Celery ──
    payload = request.model_dump(mode="json")
    process_automation_job.delay(payload)

    logger.info(
        "job_encolado",
        job_uuid=job.uuid,
        job_type=job.type,
        empresa=request.empresa.razon_social,
        trabajador=f"{request.trabajador.nombres} {request.trabajador.apellidos}",
    )

    return AcceptedResponse(job_uuid=job.uuid)


# ── Adaptadores disponibles ──

@app.get("/adapters")
async def list_available_adapters(_token: str = Depends(verify_token)):
    """Lista todos los adaptadores EPS registrados y su metadata."""
    from app.adapters.registry import list_adapters

    return {"adapters": list_adapters()}


# ── Estado de un job (consulta a Celery) ──

@app.get("/automation/jobs/{job_uuid}/status")
async def get_job_status(job_uuid: str, _token: str = Depends(verify_token)):
    """Consulta el estado de un job en Celery."""
    from celery.result import AsyncResult

    result = AsyncResult(job_uuid, app=process_automation_job.app)

    return {
        "job_uuid": job_uuid,
        "state": result.state,
        "result": result.result if result.ready() else None,
    }


# ── Demo: Extracción con IA (GitHub Models — GPT-4o-mini Vision) ──

@app.post("/demo/ocr")
async def demo_ocr(file: UploadFile = File(...)):
    """Endpoint de demostración con IA: sube un PDF y la IA extrae los datos.

    Usa GitHub Models (gratis) con GPT-4o-mini Vision.
    Requiere GITHUB_TOKEN en el archivo .env
    """
    import tempfile

    from app.services.ai_extractor import extract_with_ai

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo excede 10 MB")

    # Guardar temporalmente
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = extract_with_ai(tmp_path)
        data = result.extracted_data.model_dump(exclude_none=True)

        # Vista previa del payload completo que Laravel recibiría en el callback
        callback_preview = {
            "job_uuid": "<generado-por-laravel>",
            "incapacidad_uuid": "<uuid-incapacidad>",
            "event": "job_completed",
            "status": "success",
            "result": {
                "ocr": {
                    "status": "processed",
                    "extracted_data": data,
                    "confidence": result.confidence,
                },
                "adres": {
                    "status": "pending",
                    "fecha_validacion": None,
                    "eps_encontrada": None,
                    "estado_afiliacion": None,
                    "coincide_con_eps_laravel": None,
                },
                "rethus": {
                    "status": "pending",
                    "medico": {
                        "nombre": data.get("medico_nombre"),
                        "registro_medico": data.get("registro_medico"),
                        "especialidad": None,
                        "rethus": "PENDIENTE",
                    },
                },
            },
        }

        return {
            "status": "processed",
            "archivo": file.filename,
            "engine": "github-models-gpt-4o-mini",
            "extracted_data": data,
            "confidence": result.confidence,
            "needs_review": [],
            "callback_preview": callback_preview,
        }
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("ai_extraction_error")
        raise HTTPException(status_code=500, detail=f"Error en extracción IA: {e}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Demo: Validación RETHUS (consulta real al portal MinSalud) ──

from pydantic import BaseModel, Field


class RethusRequest(BaseModel):
    registro_medico: str | None = Field(
        default=None,
        description="Número de registro RETHUS (suele coincidir con la cédula del médico)",
        examples=["1019093117"],
    )
    medico_nombre: str | None = Field(
        default=None,
        description="Nombre del médico (opcional, se usa como fallback)",
        examples=["DR. ANDRES FELIPE TIJO"],
    )
    tipo_documento: str = Field(
        default="CC",
        description="Tipo de documento: CC, CE, PT, TI",
        examples=["CC"],
    )
    numero_documento: str | None = Field(
        default=None,
        description="Número de documento del médico. Si se omite, se usa registro_medico.",
    )


@app.post("/demo/rethus", tags=["validaciones"])
async def demo_rethus(payload: RethusRequest):
    """Consulta RETHUS (MinSalud) en vivo vía Playwright + Tesseract OCR para captcha.

    Portal real: https://web.sispro.gov.co/THS/Cliente/ConsultasPublicas/ConsultaPublicaDeTHxIdentificacion.aspx

    Devuelve nombre completo y estado (Vigente/Inactivo) del profesional.
    Tarda ~7-15 segundos por consulta (resuelve captcha con OCR local, gratis).
    """
    from anyio import to_thread

    from app.services.rethus_validator import validate_rethus

    if not (payload.registro_medico or payload.numero_documento):
        raise HTTPException(
            status_code=400,
            detail="Debes enviar al menos 'registro_medico' o 'numero_documento'",
        )

    try:
        result = await to_thread.run_sync(
            lambda: validate_rethus(
                registro_medico=payload.registro_medico,
                medico_nombre=payload.medico_nombre,
                tipo_documento=payload.tipo_documento,
                numero_documento=payload.numero_documento,
            )
        )
        return result.model_dump()
    except Exception as e:
        logger.exception("rethus_endpoint_error")
        raise HTTPException(status_code=500, detail=f"Error consultando RETHUS: {e}")


# ── Demo: Login a portales EPS (Sura / Salud Total) ──

@app.post("/demo/eps/sura/login", tags=["eps"])
async def demo_sura_login():
    """Ejecuta login REAL en EPS Sura usando credenciales del .env.

    Devuelve estado (success / invalid_credentials / blocked / error),
    URL final, mensaje del portal y rutas a screenshots de evidencia.
    """
    from anyio import to_thread
    from app.services.eps_login import login_sura

    result = await to_thread.run_sync(login_sura)
    return result.model_dump()


@app.post("/demo/eps/salud-total/login", tags=["eps"])
async def demo_salud_total_login():
    """Ejecuta login REAL en Salud Total Oficina Virtual (pestaña EMPLEADORES).

    Sin reCAPTCHA. Llena los 4 campos (empleador + usuario + clave) y reporta
    si el portal aceptó o rechazó las credenciales.
    """
    from anyio import to_thread
    from app.services.eps_login import login_salud_total

    result = await to_thread.run_sync(login_salud_total)
    return result.model_dump()


@app.get("/demo/eps/evidencia/{ruta:path}", tags=["eps"])
async def demo_eps_evidencia(ruta: str):
    """Sirve un archivo de evidencia (screenshot PNG) generado por los demos."""
    base = Path(__file__).resolve().parents[1] / "scripts" / "_inspect"
    target = (base / ruta).resolve()
    if not str(target).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Ruta inválida")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Evidencia no encontrada")
    return FileResponse(target)


@app.post("/demo/adres/validar", tags=["adres"])
async def demo_adres_validar(
    tipo_documento: str = "CC",
    numero_documento: str = "1001911185",
    eps_laravel: str = "SURA",
):
    """Ejecuta validación ADRES real. Si el portal exige captcha invisible,
    devuelve status=manual_verification_required con metadata + screenshot."""
    from anyio import to_thread
    from app.services.adres_validator import validate_adres

    result = await to_thread.run_sync(
        validate_adres, tipo_documento, numero_documento, None, eps_laravel,
    )
    return result.model_dump()


@app.post("/demo/adres/asistido", tags=["adres"])
async def demo_adres_asistido(
    tipo_documento: str = "CC",
    numero_documento: str = "1001911185",
    eps_laravel: str = "SURA",
    wait_seconds: int = 180,
):
    """Modo asistido: lanza Chrome (si no está activo), rellena los inputs,
    espera a que el humano pulse Consultar (resolviendo el captcha) y luego
    el bot lee el resultado y lo devuelve como JSON."""
    from anyio import to_thread
    from app.services.adres_validator import validate_adres_assisted

    # Asegurar que Chrome CDP está corriendo; si no, lanzarlo
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    cdp_active = s.connect_ex(("127.0.0.1", 9222)) == 0
    s.close()
    if not cdp_active:
        await demo_adres_cdp_launch()

    result = await to_thread.run_sync(
        validate_adres_assisted, tipo_documento, numero_documento, None, eps_laravel, wait_seconds,
    )
    return result.model_dump()


@app.get("/demo/adres/cdp-status", tags=["adres"])
async def demo_adres_cdp_status():
    """Indica si el Chrome del usuario está activo en CDP (modo automático)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        active = s.connect_ex(("127.0.0.1", 9222)) == 0
    finally:
        s.close()
    return {
        "cdp_active": active,
        "port": 9222,
        "launch_script": "powershell -ExecutionPolicy Bypass -File scripts\\launch_chrome_adres.ps1",
        "hint": (
            "Ejecuta el script en PowerShell para activar el modo automático. "
            "Luego en el Chrome que abre, haz UNA consulta manual de prueba "
            "para calentar el captcha invisible."
        ),
    }


@app.post("/demo/adres/cdp-launch", tags=["adres"])
async def demo_adres_cdp_launch():
    """Lanza Chrome con CDP automáticamente desde el servidor (solo dev/local)."""
    import os
    import socket
    import subprocess

    # Si ya está activo, no relanzar
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        if s.connect_ex(("127.0.0.1", 9222)) == 0:
            return {"status": "already_running", "port": 9222}
    finally:
        s.close()

    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if not Path(chrome_path).exists():
        raise HTTPException(status_code=500, detail=f"Chrome no encontrado en {chrome_path}")

    profile = Path(os.environ.get("USERPROFILE", "")) / "chrome-adres-profile"
    profile.mkdir(parents=True, exist_ok=True)

    args = [
        chrome_path,
        "--remote-debugging-port=9222",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
    ]

    # Detached para que no bloquee uvicorn y sobreviva al request
    DETACHED = 0x00000008  # DETACHED_PROCESS
    NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        args,
        creationflags=DETACHED | NEW_GROUP,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    # Esperar hasta 8s a que el puerto abra
    import time
    for _ in range(16):
        time.sleep(0.5)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            if s.connect_ex(("127.0.0.1", 9222)) == 0:
                return {"status": "launched", "port": 9222, "profile": str(profile)}
        finally:
            s.close()

    return {"status": "launched_pending", "port": 9222, "profile": str(profile),
            "hint": "Chrome se lanzó pero el puerto aún no responde. Verifica en unos segundos."}
