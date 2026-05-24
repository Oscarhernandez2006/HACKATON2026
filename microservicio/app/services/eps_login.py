"""Servicio de login a portales EPS (Sura y Salud Total) vía Playwright.

Modo demo: prueba que el RPA puede llegar al portal real, autenticarse y
detectar resultado (login exitoso vs credenciales inválidas). Guarda evidencia
en disco (screenshots + storage_state).
"""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Literal

from playwright.sync_api import sync_playwright
from pydantic import BaseModel

from app.logger import get_logger

logger = get_logger(__name__)

# Cargar .env explícitamente (el server uvicorn no lo carga por defecto)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
EVIDENCE_ROOT = Path(__file__).resolve().parents[2] / "scripts" / "_inspect"


class EPSLoginResult(BaseModel):
    eps: str
    status: Literal["success", "invalid_credentials", "blocked", "error"]
    message: str
    portal_url: str
    final_url: str = ""
    duration_seconds: float = 0.0
    evidencias: list[dict] = []


def _save_evidence(eps: str, files: list[tuple[str, Path]]) -> list[dict]:
    return [{"tipo": tipo, "path": str(p)} for tipo, p in files if p.exists()]


# ── SURA ──

def login_sura() -> EPSLoginResult:
    """Login real en EPS Sura (Cuentas SURA SSO).

    Portal usa Imperva Incapsula + cifrado client-side (crypto-js). Maneja teclado
    virtual jQuery UI que intercepta clicks → bypaseamos con click(force=True).
    """
    url = os.getenv("EPS_SURA_URL")
    user = os.getenv("EPS_SURA_USER")
    pwd = os.getenv("EPS_SURA_PASS")
    if not (url and user and pwd):
        return EPSLoginResult(
            eps="sura", status="error", portal_url=url or "",
            message="Faltan EPS_SURA_URL / USER / PASS en .env",
        )

    job_id = uuid.uuid4().hex[:8]
    out = EVIDENCE_ROOT / f"sura_{job_id}"
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()

            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_selector("#suraName", timeout=20000)
            f1 = out / "01_login_form.png"
            page.screenshot(path=str(f1), full_page=True)

            page.select_option("#ctl00_ContentMain_suraType", label="CEDULA")
            page.fill("#suraName", user)
            page.fill("#suraPassword", pwd)
            # Cerrar teclado virtual jQuery
            page.evaluate("document.getElementById('suraPassword').blur()")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            f2 = out / "02_filled.png"
            page.screenshot(path=str(f2), full_page=True)

            try:
                page.click("#session-internet", force=True, timeout=10000)
            except Exception:
                page.evaluate("document.getElementById('session-internet').click()")
            page.wait_for_timeout(8000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            f3 = out / "03_after_login.png"
            page.screenshot(path=str(f3), full_page=True)
            final_url = page.url
            title = page.title()
            body = (page.evaluate("() => document.body.innerText") or "").lower()
            duration = round(time.time() - start, 2)
            ctx.storage_state(path=str(out / "storage_state.json"))
            browser.close()

        evidencias = _save_evidence("sura", [
            ("screenshot", f1), ("screenshot", f2), ("comprobante", f3),
        ])

        # Diagnóstico
        if "login" not in final_url.lower():
            return EPSLoginResult(
                eps="sura", status="success", portal_url=url, final_url=final_url,
                duration_seconds=duration,
                message=f"Login exitoso. Title='{title}'", evidencias=evidencias,
            )
        if any(kw in body for kw in ["incorrect", "no coincide", "inválid"]):
            return EPSLoginResult(
                eps="sura", status="invalid_credentials", portal_url=url, final_url=final_url,
                duration_seconds=duration,
                message="Portal rechazó las credenciales", evidencias=evidencias,
            )
        return EPSLoginResult(
            eps="sura", status="blocked", portal_url=url, final_url=final_url,
            duration_seconds=duration,
            message="Form no se submitió. Probable WAF Imperva Incapsula detectó automatización.",
            evidencias=evidencias,
        )
    except Exception as e:
        logger.exception("sura_login_error")
        return EPSLoginResult(
            eps="sura", status="error", portal_url=url,
            message=f"Excepción: {e}",
            duration_seconds=round(time.time() - start, 2),
        )


# ── SALUD TOTAL ──

_TIPO_MAP_ST = {
    "CC": "CEDULA DE CIUDADANIA",
    "NIT": "NIT",
    "CE": "CEDULA DE EXTRANJERIA",
    "TI": "TARJETA DE IDENTIDAD",
    "PT": "PERMISO POR PROTECCION TEMPORAL",
    "PA": "PASAPORTE",
}


def _pick_kendo_combobox(page, input_el, label_substring: str) -> str | None:
    input_el.click()
    page.wait_for_timeout(300)
    input_el.fill("")
    input_el.type(label_substring, delay=40)
    page.wait_for_timeout(800)
    for o in page.query_selector_all("ul.k-list li.k-item"):
        try:
            if not o.is_visible():
                continue
            txt = (o.inner_text() or "").upper().strip()
            if label_substring.upper() in txt:
                o.click()
                page.wait_for_timeout(300)
                return txt
        except Exception:
            pass
    return None


def login_salud_total() -> EPSLoginResult:
    """Login real Salud Total Oficina Virtual — pestaña EMPLEADORES (4 campos).

    Stack: Angular + Kendo UI. Sin reCAPTCHA. .env esperado:
        EPS_SALUD_TOTAL_USER='NIT 901240743 - CC 1001911185'
    """
    url = os.getenv("EPS_SALUD_TOTAL_URL")
    user_raw = os.getenv("EPS_SALUD_TOTAL_USER", "")
    pwd = os.getenv("EPS_SALUD_TOTAL_PASS")

    pairs = re.findall(r"(NIT|CC|CE|TI|PT)\s+([\dA-Z]+)", user_raw, re.I)
    if not (url and pwd) or len(pairs) < 2:
        return EPSLoginResult(
            eps="salud_total", status="error", portal_url=url or "",
            message="Config inválida. Formato esperado USER: 'NIT xxx - CC yyy'",
        )
    emp_tipo, emp_num = pairs[0][0].upper(), pairs[0][1]
    usr_tipo, usr_num = pairs[1][0].upper(), pairs[1][1]

    job_id = uuid.uuid4().hex[:8]
    out = EVIDENCE_ROOT / f"salud_total_{job_id}"
    out.mkdir(parents=True, exist_ok=True)
    start = time.time()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(user_agent=UA)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(2500)
            f1 = out / "01_home.png"
            page.screenshot(path=str(f1), full_page=True)

            tab = page.query_selector("li[role='tab']:has-text('EMPLEADORES')")
            if not tab:
                browser.close()
                return EPSLoginResult(
                    eps="salud_total", status="error", portal_url=url,
                    message="Pestaña EMPLEADORES no encontrada",
                    duration_seconds=round(time.time() - start, 2),
                )
            tab.click()
            page.wait_for_timeout(2000)
            page.wait_for_selector(
                "input[placeholder='NÚMERO DE DOCUMENTO DEL EMPLEADOR']", timeout=20000,
            )
            f2 = out / "02_tab_empleadores.png"
            page.screenshot(path=str(f2), full_page=True)

            # Llenar 4 campos
            emp_in = page.query_selector("input[placeholder='TIPO DE DOCUMENTO DEL EMPLEADOR']")
            _pick_kendo_combobox(page, emp_in, _TIPO_MAP_ST.get(emp_tipo, emp_tipo))
            page.fill("input[placeholder='NÚMERO DE DOCUMENTO DEL EMPLEADOR']", emp_num)
            usr_in = page.query_selector("input[placeholder='TIPO DE DOCUMENTO DEL USUARIO']")
            _pick_kendo_combobox(page, usr_in, _TIPO_MAP_ST.get(usr_tipo, usr_tipo))
            page.fill("input[placeholder='NÚMERO DE DOCUMENTO DEL USUARIO']", usr_num)
            page.fill("input[placeholder='CONTRASEÑA']", pwd)

            chk = page.query_selector("input[type=checkbox]")
            if chk and chk.is_visible():
                try:
                    chk.check()
                except Exception:
                    pass

            f3 = out / "03_filled.png"
            page.screenshot(path=str(f3), full_page=True)

            page.click("button:has-text('INGRESAR')")
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            page.wait_for_timeout(6000)
            f4 = out / "04_after.png"
            page.screenshot(path=str(f4), full_page=True)

            final_url = page.url
            title = page.title()
            body = (page.evaluate("() => document.body.innerText") or "")
            body_low = body.lower()
            duration = round(time.time() - start, 2)
            ctx.storage_state(path=str(out / "storage_state.json"))
            browser.close()

        evidencias = _save_evidence("salud_total", [
            ("screenshot", f1), ("screenshot", f2), ("screenshot", f3),
            ("comprobante", f4),
        ])

        # Mensaje de error explícito de Salud Total
        m = re.search(r"(la clave ingresada[^\n.]{5,200})", body, re.I)
        portal_msg = m.group(1).strip() if m else ""

        if "no coincide" in body_low or "credencial" in body_low or "incorrect" in body_low:
            return EPSLoginResult(
                eps="salud_total", status="invalid_credentials", portal_url=url,
                final_url=final_url, duration_seconds=duration,
                message=f"Portal rechazó credenciales: {portal_msg or 'no coincide'}",
                evidencias=evidencias,
            )
        # Si cambió a una ruta SPA distinta de '#/' es éxito
        if "#/" in final_url and len(final_url.rsplit("#/", 1)[-1]) > 1:
            return EPSLoginResult(
                eps="salud_total", status="success", portal_url=url,
                final_url=final_url, duration_seconds=duration,
                message=f"Login exitoso. Title='{title}'",
                evidencias=evidencias,
            )
        return EPSLoginResult(
            eps="salud_total", status="error", portal_url=url,
            final_url=final_url, duration_seconds=duration,
            message="Estado indeterminado, revisa screenshot 04_after",
            evidencias=evidencias,
        )
    except Exception as e:
        logger.exception("salud_total_login_error")
        return EPSLoginResult(
            eps="salud_total", status="error", portal_url=url,
            message=f"Excepción: {e}",
            duration_seconds=round(time.time() - start, 2),
        )
