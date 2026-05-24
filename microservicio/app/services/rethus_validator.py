"""Validador RETHUS — consulta real con Playwright + GPT-4o Vision para captcha.

URL: https://web.sispro.gov.co/THS/Cliente/ConsultasPublicas/ConsultaPublicaDeTHxIdentificacion.aspx
Captcha: imagen PNG con números, resuelto con GPT-4o-mini Vision (GitHub Models).
"""

from __future__ import annotations

import base64
import re

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

from app.config import get_settings
from app.logger import get_logger
from app.schemas import RethusResult, RethusValidatedMedico

logger = get_logger(__name__)

RETHUS_URL = "https://web.sispro.gov.co/THS/Cliente/ConsultasPublicas/ConsultaPublicaDeTHxIdentificacion.aspx"

_TIPO_DOC = {"CC": "CC", "CE": "CE", "TI": "TI", "PT": "PT"}


def validate_rethus(
    registro_medico: str | None = None,
    medico_nombre: str | None = None,
    tipo_documento: str | None = "CC",
    numero_documento: str | None = None,
) -> RethusResult:
    """Valida un profesional médico en RETHUS vía Playwright.

    En Colombia, el "registro médico" RFP suele ser la cédula del profesional,
    así que si no llega numero_documento usamos el registro.
    """
    settings = get_settings()
    doc_to_query = numero_documento or registro_medico
    if not doc_to_query:
        return RethusResult(status="invalid", medico=None)

    tipo = _TIPO_DOC.get((tipo_documento or "CC").upper(), "CC")

    logger.info(
        "rethus_consulta_iniciada",
        tipo=tipo,
        doc_parcial=f"***{doc_to_query[-4:]}",
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(settings.playwright_timeout)

            page.goto(RETHUS_URL, wait_until="domcontentloaded")
            page.wait_for_selector("#ctl00_cntContenido_ddlTipoIdentificacion")

            page.select_option("#ctl00_cntContenido_ddlTipoIdentificacion", tipo)
            page.fill("#ctl00_cntContenido_txtNumeroIdentificacion", doc_to_query)

            # Resolver captcha con hasta 8 intentos
            captcha_ok = False
            for intento in range(1, 9):
                captcha_text = _solve_captcha(page)
                if not captcha_text:
                    logger.warning("rethus_captcha_no_resuelto", intento=intento)
                    page.evaluate("ChangeCaptcha()")
                    page.wait_for_timeout(800)
                    continue

                logger.info("rethus_captcha_resuelto", intento=intento, valor=captcha_text)
                page.fill("#ctl00_cntContenido_txtCatpchaConfirmation", captcha_text)
                page.click("#ctl00_cntContenido_btnVerificarIdentificacion")
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(1200)

                body_text = page.inner_text("body")
                # El validador ASP.NET muestra el span de error con display:inline cuando falla
                captcha_failed = False
                try:
                    style = page.get_attribute("#ctl00_cntContenido_cvlValCaptcha", "style") or ""
                    if "display: inline" in style or "display:inline" in style:
                        captcha_failed = True
                except Exception:
                    pass
                if (
                    captcha_failed
                    or "Verifique el Número" in body_text
                    or "Verifique el NÃºmero" in body_text
                ):
                    logger.warning("rethus_captcha_incorrecto", intento=intento)
                    page.evaluate("ChangeCaptcha()")
                    page.wait_for_timeout(800)
                    # Re-poblar campos por si se limpiaron
                    page.select_option("#ctl00_cntContenido_ddlTipoIdentificacion", tipo)
                    page.fill("#ctl00_cntContenido_txtNumeroIdentificacion", doc_to_query)
                    continue
                captcha_ok = True
                break

            if not captcha_ok:
                browser.close()
                return RethusResult(
                    status="error",
                    medico=_minimal_medico(medico_nombre, registro_medico, "ERROR_CAPTCHA"),
                )

            html = page.content()
            text = page.inner_text("body")

            # Guardar evidencia
            try:
                from pathlib import Path
                Path("scripts/_inspect").mkdir(parents=True, exist_ok=True)
                Path("scripts/_inspect/rethus_result.html").write_text(html, encoding="utf-8")
                page.screenshot(path="scripts/_inspect/rethus_result.png", full_page=True)
            except Exception:
                pass

            browser.close()

    except PWTimeout:
        logger.exception("rethus_timeout")
        return RethusResult(
            status="error",
            medico=_minimal_medico(medico_nombre, registro_medico, "TIMEOUT"),
        )
    except Exception:
        logger.exception("rethus_error")
        return RethusResult(
            status="error",
            medico=_minimal_medico(medico_nombre, registro_medico, "ERROR"),
        )

    # Captcha incorrecto
    if "Número de Confirmación" in text or "VerificaciÃ³n del" in text:
        # Si los validators de ASP.NET dispararon, el formulario no se envió
        if "Verifique el Número" in text or "Verifique el NÃºmero" in text:
            logger.warning("rethus_captcha_incorrecto")
            return RethusResult(
                status="error",
                medico=_minimal_medico(medico_nombre, registro_medico, "CAPTCHA_INVALIDO"),
            )

    # No encontrado
    if re.search(r"no se encontr|sin resultados|no existe|no presenta registros", text, re.IGNORECASE):
        logger.warning("rethus_no_encontrado")
        return RethusResult(
            status="not_found",
            medico=_minimal_medico(medico_nombre, registro_medico, "NO_ENCONTRADO"),
        )

    nombre = _extract_nombre(html, text) or (medico_nombre or "DESCONOCIDO")
    especialidad = _extract_especialidad(html, text)
    estado = _extract_estado(text)

    valido = estado in ("ACTIVO", "HABILITADO", "VIGENTE") or "tiene registro" in text.lower()

    logger.info(
        "rethus_validacion_ok",
        nombre=nombre,
        estado=estado,
        especialidad=especialidad,
        valido=valido,
    )

    return RethusResult(
        status="success" if valido else "invalid",
        medico=RethusValidatedMedico(
            nombre=nombre.upper(),
            registro_medico=registro_medico or doc_to_query,
            especialidad=especialidad,
            rethus="VALIDADO" if valido else "NO_VALIDADO",
        ),
    )


def _solve_captcha(page) -> str | None:
    """Descarga la imagen del captcha y la resuelve con Tesseract OCR local."""
    try:
        img = page.query_selector("#imgCaptcha")
        if not img:
            return None
        img_bytes = img.screenshot()
        # Guardar para debug
        try:
            from pathlib import Path
            Path("scripts/_inspect").mkdir(parents=True, exist_ok=True)
            Path("scripts/_inspect/rethus_captcha.png").write_bytes(img_bytes)
        except Exception:
            pass
    except Exception:
        logger.exception("captcha_screenshot_error")
        return None

    try:
        import io
        import pytesseract
        from PIL import Image, ImageOps, ImageFilter

        # Windows: configurar ruta a tesseract.exe si no está en PATH
        import os, shutil
        if not shutil.which("tesseract"):
            for p in (
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
            ):
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    break

        img = Image.open(io.BytesIO(img_bytes))
        # Preprocesar: escala de grises, upscaling, binarizar
        img = img.convert("L")
        img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img = img.point(lambda x: 0 if x < 140 else 255, mode="1")

        # OCR: sólo dígitos, una línea
        config = "--psm 7 -c tessedit_char_whitelist=0123456789"
        raw = pytesseract.image_to_string(img, config=config)
        cleaned = re.sub(r"[^0-9]", "", raw).strip()
        logger.info("captcha_ocr_raw", raw=raw.strip(), cleaned=cleaned)
        return cleaned or None
    except Exception:
        logger.exception("captcha_ocr_error")
        return None


def _minimal_medico(nombre: str | None, registro: str | None, estado: str):
    return RethusValidatedMedico(
        nombre=(nombre or "DESCONOCIDO").upper(),
        registro_medico=registro or "N/A",
        especialidad=None,
        rethus=estado,
    )


def _extract_nombre(html: str, text: str) -> str | None:
    # Estructura RETHUS: tabla con cols Tipo|Nro|PNombre|SNombre|PApellido|SApellido|Estado
    # Buscamos la fila de datos después del header
    m = re.search(
        r"(CC|CE|TI|PT)\s+(\d{5,})\s+([A-ZÁÉÍÓÚÑ]+)(?:\s+([A-ZÁÉÍÓÚÑ]+))?\s+([A-ZÁÉÍÓÚÑ]+)(?:\s+([A-ZÁÉÍÓÚÑ]+))?\s+(Vigente|Inactivo|Activo)",
        text,
    )
    if m:
        partes = [m.group(i) for i in (3, 4, 5, 6) if m.group(i)]
        return " ".join(partes)
    # Fallback: etiquetas
    for label in ("Nombre Completo", "Nombres y Apellidos", "Profesional"):
        mm = re.search(rf"{label}[^<]*</[^>]+>\s*<[^>]+>([^<]+)<", html, re.IGNORECASE)
        if mm:
            v = mm.group(1).strip()
            if len(v) > 2:
                return v
    return None


def _extract_especialidad(html: str, text: str) -> str | None:
    for label in ("Especialidad", "Profesión", "Profesion", "Título"):
        m = re.search(rf"{label}[^<]*</[^>]+>\s*<[^>]+>([^<]+)<", html, re.IGNORECASE)
        if m:
            return m.group(1).strip().upper()
    return None


def _extract_estado(text: str) -> str | None:
    # Buscar Estado en la tabla de RETHUS (formato: "TIJO GARAVITO Vigente")
    m = re.search(r"\b(Vigente|Activo|Inactivo|Suspendido|Habilitado)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return None
