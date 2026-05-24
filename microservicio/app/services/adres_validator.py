"""Validador ADRES — consulta real con Playwright al portal BDUA.

URL: https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx

NOTA: El portal usa reCAPTCHA Enterprise INVISIBLE (sitekey
6LdjqjksAAAAAAduGUnDTl7-kSoeSDI7S-vAazXp). Cuando el score de Google es bajo,
la consulta se rechaza silenciosamente sin devolver datos. En ese caso el
validador devuelve status="manual_verification_required" con metadata para que
el operador resuelva la consulta en el portal y reporte el resultado.
Upgrade path: integrar 2Captcha Enterprise API (~USD 3 / 1000 consultas).
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import date
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

from app.config import get_settings
from app.logger import get_logger
from app.schemas import AdresResult

logger = get_logger(__name__)

ADRES_URL = "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx"
ADRES_PUBLIC_URL = "https://www.adres.gov.co/consulte-su-eps"
EVIDENCE_ROOT = Path(__file__).resolve().parents[2] / "scripts" / "_inspect"

_TIPO_DOC = {
    "CC": "CC", "TI": "TI", "CE": "CE", "PA": "PA", "RC": "RC",
    "NU": "NU", "AS": "AS", "MS": "MS", "CD": "CD", "CN": "CN",
    "SC": "SC", "PE": "PE", "PT": "PT",
    "NIT": "CC",
}


def validate_adres(
    tipo_documento: str,
    numero_documento: str,
    fecha_inicio: str | None,
    eps_laravel: str,
) -> AdresResult:
    """Consulta la afiliación del trabajador en ADRES (BDUA) vía Playwright."""
    if not fecha_inicio:
        fecha_inicio = date.today().isoformat()

    settings = get_settings()
    tipo = _TIPO_DOC.get(tipo_documento.upper(), "CC")

    logger.info(
        "adres_consulta_iniciada",
        tipo=tipo,
        doc_parcial=f"***{numero_documento[-4:]}",
        fecha=fecha_inicio,
    )

    try:
        with sync_playwright() as p:
            # Estrategia 1: intentar conectar al Chrome del usuario via CDP
            # (lanzado con scripts/launch_chrome_adres.ps1). Si está activo,
            # la consulta usa la sesión real del usuario y pasa el reCAPTCHA
            # Enterprise invisible. Si no, cae al modo headless estándar.
            browser = None
            context = None
            page = None
            cdp_mode = False
            opened_new_page = False
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222", timeout=2500)
                # Reusar el contexto existente (donde ya hay cookies + score alto)
                if browser.contexts:
                    context = browser.contexts[0]
                else:
                    context = browser.new_context()
                # CRÍTICO: reusar una pestaña que ya tenga ADRES cargado (calentada
                # por el usuario). Si abrimos pestaña nueva, Google regenera el
                # token con score bajo y la consulta vuelve a ser bloqueada.
                for existing in context.pages:
                    if "adres.gov.co" in (existing.url or ""):
                        page = existing
                        logger.info("adres_cdp_reuse_page", url=existing.url)
                        break
                if page is None:
                    page = context.new_page()
                    opened_new_page = True
                    logger.info("adres_cdp_new_page_fallback")
                cdp_mode = True
                logger.info("adres_cdp_attach_ok")
            except Exception:
                browser = p.chromium.launch(headless=settings.playwright_headless)
                context = browser.new_context()
                page = context.new_page()

            page.set_default_timeout(settings.playwright_timeout)

            # Si la pestaña reusada no está en la página de consulta, navegar
            current = (page.url or "").lower()
            if "consultaraffiliadoweb" not in current and "consultarafiliadoweb" not in current:
                page.goto(ADRES_URL, wait_until="domcontentloaded")

            # Anti-detección básica (sólo afecta a la pestaña actual)
            try:
                page.evaluate("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            except Exception:
                pass

            page.wait_for_selector("#tipoDoc", timeout=10000)

            # Simular interacción humana mínima para subir score reCAPTCHA
            page.mouse.move(200, 200)
            page.wait_for_timeout(300)
            page.mouse.move(400, 350, steps=8)
            page.wait_for_timeout(200)

            page.select_option("#tipoDoc", tipo)
            page.wait_for_timeout(400)
            page.fill("#txtNumDoc", "")
            page.type("#txtNumDoc", numero_documento, delay=80)
            page.wait_for_timeout(500)
            page.mouse.move(500, 450, steps=6)
            page.wait_for_timeout(200)
            page.click("#btnConsultar")

            # Esperar a que aparezca tabla resultado o mensaje de error
            try:
                page.wait_for_function(
                    """() => {
                        const t = document.querySelector('table.dataTable, table#GridView1, table[id*=Grid]');
                        const err = document.querySelector('#Error');
                        const errTxt = err ? err.innerText.trim() : '';
                        return (t && t.querySelectorAll('tr').length > 1) || errTxt.length > 0;
                    }""",
                    timeout=20000,
                )
            except Exception:
                pass
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(1500)

            html = page.content()
            text = page.inner_text("body")

            # Evidencia única por consulta
            run_id = uuid.uuid4().hex[:8]
            ev_dir = EVIDENCE_ROOT / f"adres_{run_id}"
            ev_dir.mkdir(parents=True, exist_ok=True)
            (ev_dir / "adres_result.html").write_text(html, encoding="utf-8")
            screenshot_path = ev_dir / "adres_result.png"
            page.screenshot(path=str(screenshot_path), full_page=True)

            # En CDP attach NO cerramos el browser (es el Chrome del usuario);
            # sólo cerramos la pestaña si la abrimos nosotros (no la del usuario).
            if cdp_mode:
                if opened_new_page:
                    try: page.close()
                    except Exception: pass
            else:
                browser.close()

    except PWTimeout:
        logger.exception("adres_timeout")
        return AdresResult(status="error", fecha_validacion=fecha_inicio)
    except Exception:
        logger.exception("adres_error")
        return AdresResult(status="error", fecha_validacion=fecha_inicio)

    # Detectar bloqueo por captcha invisible: el portal regresa el formulario
    # vacío sin tabla de resultados ni mensaje de "no encontrado".
    has_result_table = bool(re.search(r"<table[^>]*(?:id|class)=[^>]*(?:Grid|result|afiliado)", html, re.IGNORECASE))
    has_not_found = bool(re.search(r"no se encontr|sin afiliaci|no presenta|sin registros", text, re.IGNORECASE))
    captcha_present = "g-recaptcha-response" in html or "recaptcha" in html.lower()

    # URLs servibles para el dashboard
    rel_png = screenshot_path.relative_to(EVIDENCE_ROOT).as_posix()
    ev_screenshot = f"/demo/eps/evidencia/{rel_png}"
    ev_html = f"/demo/eps/evidencia/{(ev_dir / 'adres_result.html').relative_to(EVIDENCE_ROOT).as_posix()}"

    if not has_result_table and not has_not_found and captcha_present:
        logger.warning("adres_captcha_bloqueo", run_id=run_id)
        return AdresResult(
            status="manual_verification_required",
            fecha_validacion=fecha_inicio,
            evidencia_screenshot=ev_screenshot,
            evidencia_html=ev_html,
            manual_verification={
                "reason": "recaptcha_enterprise_invisible",
                "sitekey": "6LdjqjksAAAAAAduGUnDTl7-kSoeSDI7S-vAazXp",
                "portal_url": ADRES_PUBLIC_URL,
                "consulta_url": ADRES_URL,
                "tipo_documento": tipo,
                "numero_documento": numero_documento,
                "evidencia_screenshot": ev_screenshot,
                "instrucciones": (
                    "El portal ADRES protege la consulta con reCAPTCHA Enterprise "
                    "invisible cuyo token está ligado a IP+UA del cliente que lo "
                    "emite, por lo que no es delegable al servidor. Resuelva la "
                    "consulta manualmente en el portal y registre el resultado "
                    "en el sistema, o habilite la integración 2Captcha Enterprise "
                    "para automatización completa."
                ),
            },
        )

    if has_not_found:
        logger.warning("adres_no_encontrado")
        return AdresResult(
            status="not_found",
            fecha_validacion=fecha_inicio,
            evidencia_screenshot=ev_screenshot,
            evidencia_html=ev_html,
        )

    eps = _extract_eps_from_table(html)
    estado = _extract_estado_from_table(html)

    eps_norm = _normalize_eps(eps) if eps else None
    laravel_norm = _normalize_eps(eps_laravel) if eps_laravel else None
    coincide = eps_norm == laravel_norm if eps_norm and laravel_norm else None

    logger.info(
        "adres_validacion_ok",
        eps_encontrada=eps,
        estado=estado,
        coincide=coincide,
    )

    return AdresResult(
        status="success" if eps else "not_found",
        fecha_validacion=fecha_inicio,
        eps_encontrada=eps,
        estado_afiliacion=estado,
        coincide_con_eps_laravel=coincide,
        evidencia_screenshot=ev_screenshot,
        evidencia_html=ev_html,
    )


def _extract_eps_from_table(html: str) -> str | None:
    cells = re.findall(r"<td[^>]*>([^<]+)</td>", html, re.IGNORECASE)
    eps_keywords = ("EPS", "SURA", "SANITAS", "SALUD TOTAL", "COMPENSAR",
                    "NUEVA", "FAMISANAR", "MUTUAL", "COOSALUD", "COOMEVA",
                    "S.O.S", "CAJACOPI", "ASMET", "SAVIA")
    for raw in cells:
        val = raw.strip()
        if not val or len(val) < 4:
            continue
        upper = val.upper()
        if any(kw in upper for kw in eps_keywords):
            return val
    return None


def _extract_estado_from_table(html: str) -> str | None:
    text = re.sub(r"<[^>]+>", " ", html).upper()
    for k in ("ACTIVO", "INACTIVO", "SUSPENDIDO", "RETIRADO"):
        if k in text:
            return k
    return None


def _normalize_eps(name: str) -> str:
    n = name.upper().strip()
    n = re.sub(r"\b(EPS|S\.?A\.?S?\.?|E\.?P\.?S\.?|EAPB)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    aliases = {
        "SURAMERICANA": "SURA",
        "ENTIDAD PROMOTORA DE SALUD SANITAS": "SANITAS",
        "ENTIDAD PROMOTORA DE SALUD SURA": "SURA",
        "SALUD TOTAL": "SALUD_TOTAL",
        "NUEVA": "NUEVA_EPS",
        "MUTUAL SER": "MUTUAL_SER",
    }
    for alias, canonical in aliases.items():
        if alias in n:
            return canonical
    return n


def validate_adres_assisted(
    tipo_documento: str,
    numero_documento: str,
    fecha_inicio: str | None,
    eps_laravel: str,
    wait_seconds: int = 180,
) -> AdresResult:
    """Modo asistido: bot llena los inputs en el Chrome del usuario y espera
    a que el humano resuelva el captcha y haga clic en Consultar. Luego el
    bot lee el resultado, lo parsea y compara la EPS automáticamente.

    Requiere Chrome lanzado con CDP en puerto 9222.
    """
    if not fecha_inicio:
        fecha_inicio = date.today().isoformat()

    tipo = _TIPO_DOC.get(tipo_documento.upper(), "CC")

    logger.info(
        "adres_asistido_iniciado",
        tipo=tipo,
        doc_parcial=f"***{numero_documento[-4:]}",
        wait_seconds=wait_seconds,
    )

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.connect_over_cdp("http://localhost:9222", timeout=3000)
            except Exception:
                return AdresResult(
                    status="error",
                    fecha_validacion=fecha_inicio,
                    manual_verification={
                        "reason": "cdp_not_available",
                        "hint": "Chrome no está lanzado con CDP. Pulsa 'Activar modo automático' primero.",
                    },
                )

            context = browser.contexts[0] if browser.contexts else browser.new_context()

            # Reusar pestaña existente en ADRES, o navegar
            page = None
            for existing in context.pages:
                if "adres.gov.co" in (existing.url or ""):
                    page = existing
                    break
            if page is None:
                page = context.new_page()
                page.goto(ADRES_URL, wait_until="domcontentloaded")

            # Si está en la página pública (no en el formulario), navegar
            current = (page.url or "").lower()
            if "consultarafiliadoweb" not in current:
                page.goto(ADRES_URL, wait_until="domcontentloaded")

            try:
                page.bring_to_front()
            except Exception:
                pass

            page.wait_for_selector("#tipoDoc", timeout=15000)

            # Rellenar inputs por el bot
            page.select_option("#tipoDoc", tipo)
            page.wait_for_timeout(200)
            page.fill("#txtNumDoc", "")
            page.type("#txtNumDoc", numero_documento, delay=60)
            logger.info("adres_asistido_inputs_listos", esperando_click=True)

            # Snapshot de páginas existentes ANTES del click (para detectar pestañas nuevas)
            pages_before = set(id(pg) for pg in context.pages)

            # Banner visual dentro de la página para guiar al humano
            try:
                page.evaluate(
                    """(doc) => {
                        const old = document.getElementById('__bot_banner__');
                        if (old) old.remove();
                        const b = document.createElement('div');
                        b.id = '__bot_banner__';
                        b.style.cssText = 'position:fixed;top:0;left:0;right:0;background:#1a7f3a;color:#fff;padding:14px;text-align:center;font:600 14px system-ui;z-index:99999;box-shadow:0 2px 12px rgba(0,0,0,.3)';
                        b.innerHTML = '🤖 Bot listo · Documento <b>'+doc+'</b> ya cargado · resuelve el captcha (si aparece) y pulsa <b>Consultar</b> · el bot leerá el resultado automáticamente';
                        document.body.prepend(b);
                    }""",
                    numero_documento,
                )
            except Exception:
                pass

            # Esperar a que aparezca resultado. ADRES suele abrir el resultado en
            # una NUEVA pestaña, así que vigilamos tanto la pestaña original como
            # cualquier pestaña nueva del contexto.
            wait_ms = max(15000, wait_seconds * 1000)
            deadline = time.monotonic() + (wait_ms / 1000)
            result_page = None
            check_js = """() => {
                const t = document.querySelector('table.dataTable, table#GridView1, table[id*=Grid], table[id*=grid]');
                const err = document.querySelector('#Error, #lblMensaje, .text-danger, .alert-danger');
                const errTxt = err ? (err.innerText || '').trim() : '';
                const bodyTxt = (document.body && document.body.innerText) || '';
                const hasRows = t && t.querySelectorAll('tr').length > 1;
                const hasErr = errTxt.length > 0;
                const hasNotFound = /no se encontr|sin afiliaci|no presenta|sin registros/i.test(bodyTxt);
                return hasRows || hasErr || hasNotFound;
            }"""

            while time.monotonic() < deadline:
                # Revisar todas las pestañas del contexto (incluye nuevas)
                for pg in list(context.pages):
                    try:
                        url = (pg.url or "").lower()
                    except Exception:
                        continue
                    if "adres.gov.co" not in url:
                        continue
                    try:
                        if pg.evaluate(check_js):
                            result_page = pg
                            break
                    except Exception:
                        continue
                if result_page is not None:
                    break
                time.sleep(0.6)

            if result_page is None:
                logger.warning("adres_asistido_timeout_humano", wait_seconds=wait_seconds)
                return AdresResult(
                    status="manual_verification_required",
                    fecha_validacion=fecha_inicio,
                    manual_verification={
                        "reason": "timeout_humano",
                        "hint": f"El bot esperó {wait_seconds}s y no detectó resultado. Vuelve a intentar.",
                    },
                )

            # Loguear si fue pestaña nueva
            if id(result_page) not in pages_before:
                logger.info("adres_asistido_resultado_en_nueva_pestana", url=result_page.url)
            else:
                logger.info("adres_asistido_resultado_en_pestana_original", url=result_page.url)

            try:
                result_page.bring_to_front()
            except Exception:
                pass
            try:
                result_page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            result_page.wait_for_timeout(800)

            # Quitar banner si quedó en la página original
            try:
                page.evaluate("const b=document.getElementById('__bot_banner__'); if(b) b.remove();")
            except Exception:
                pass

            html = result_page.content()
            text = result_page.inner_text("body")

            run_id = uuid.uuid4().hex[:8]
            ev_dir = EVIDENCE_ROOT / f"adres_assist_{run_id}"
            ev_dir.mkdir(parents=True, exist_ok=True)
            (ev_dir / "adres_result.html").write_text(html, encoding="utf-8")
            screenshot_path = ev_dir / "adres_result.png"
            result_page.screenshot(path=str(screenshot_path), full_page=True)

    except Exception:
        logger.exception("adres_asistido_error")
        return AdresResult(status="error", fecha_validacion=fecha_inicio)

    rel_png = screenshot_path.relative_to(EVIDENCE_ROOT).as_posix()
    ev_screenshot = f"/demo/eps/evidencia/{rel_png}"
    ev_html = f"/demo/eps/evidencia/{(ev_dir / 'adres_result.html').relative_to(EVIDENCE_ROOT).as_posix()}"

    has_not_found = bool(re.search(r"no se encontr|sin afiliaci|no presenta|sin registros", text, re.IGNORECASE))

    if has_not_found:
        return AdresResult(
            status="not_found",
            fecha_validacion=fecha_inicio,
            evidencia_screenshot=ev_screenshot,
            evidencia_html=ev_html,
        )

    eps = _extract_eps_from_table(html)
    estado = _extract_estado_from_table(html)

    eps_norm = _normalize_eps(eps) if eps else None
    laravel_norm = _normalize_eps(eps_laravel) if eps_laravel else None
    coincide = eps_norm == laravel_norm if eps_norm and laravel_norm else None

    logger.info("adres_asistido_ok", eps=eps, estado=estado, coincide=coincide)

    return AdresResult(
        status="success" if eps else "not_found",
        fecha_validacion=fecha_inicio,
        eps_encontrada=eps,
        estado_afiliacion=estado,
        coincide_con_eps_laravel=coincide,
        evidencia_screenshot=ev_screenshot,
        evidencia_html=ev_html,
    )
