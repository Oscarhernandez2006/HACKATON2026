"""Prueba consulta ADRES reusando storage_state.json capturado manualmente.

Uso:
  python scripts/test_adres_with_state.py [--headed] [--cedula 1001911185] [--tipo CC]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "_inspect"
STATE_PATH = OUT / "adres_storage_state.json"
META_PATH = OUT / "adres_storage_meta.json"

# Portal de consulta directa BDUA (formulario tradicional ASPX)
ADRES_URL = "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx"


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cedula", default="1001911185")
    parser.add_argument("--tipo", default="CC")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    if not STATE_PATH.exists():
        print(f"❌ No existe {STATE_PATH}")
        print("   Ejecuta primero:  python scripts/adres_capture_session.py")
        sys.exit(1)

    if META_PATH.exists():
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(meta["captured_at"])
        age = datetime.now(timezone.utc) - captured
        print(f"📂 Sesión capturada hace {age.total_seconds()/3600:.1f} horas")
        print(f"   ({meta['cookies_count']} cookies, dominios: {meta['cookies_domains']})")

    print(f"\n🔍 Consultando ADRES: {args.tipo} {args.cedula}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            storage_state=str(STATE_PATH),
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.goto(ADRES_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "adres_state_01_loaded.png"), full_page=True)

        # Intentar llenar formulario clásico (tipoDoc, txtNumDoc, btnConsultar)
        try:
            page.wait_for_selector("#tipoDoc, select[name*='tipoDoc']", timeout=10000)
            page.select_option("#tipoDoc", args.tipo)
            page.fill("#txtNumDoc", args.cedula)
            page.screenshot(path=str(OUT / "adres_state_02_filled.png"), full_page=True)
            page.click("#btnConsultar")
        except Exception as e:
            print(f"⚠ Selectores clásicos no encontrados: {e}")
            print("   Quizás el portal cambió, o estás en URL distinta")

        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT / "adres_state_03_result.png"), full_page=True)
        (OUT / "adres_state_result.html").write_text(page.content(), encoding="utf-8")

        body = page.evaluate("() => document.body.innerText")
        print(f"\nURL final: {page.url}")
        print(f"Título: {page.title()}")
        print("\n── Primeros 800 chars del body ──")
        print(body[:800])

        # Diagnóstico
        body_low = body.lower()
        if "captcha" in body_low or "robot" in body_low or "verificación" in body_low:
            print("\n❌ Aún pide captcha — la sesión no aplicó")
        elif any(kw in body_low for kw in ["eps", "régimen", "regimen", "afiliad"]):
            print("\n✅ Consulta exitosa — la sesión funcionó")
        else:
            print("\n⚠ Estado indeterminado — revisa screenshot adres_state_03_result.png")

        browser.close()


if __name__ == "__main__":
    run()
