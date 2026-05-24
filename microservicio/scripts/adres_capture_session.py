"""Captura sesión ADRES manualmente — abre navegador, espera ENTER y guarda storage_state.

Uso:
  1. Ejecuta:  python scripts/adres_capture_session.py
  2. Se abre Chrome. Resuelve cualquier captcha/banner manualmente.
  3. Haz UNA consulta de prueba (cualquier cédula) para que el portal active la sesión.
  4. Vuelve a la terminal y presiona ENTER.
  5. Se guarda  scripts/_inspect/adres_storage_state.json  con cookies + localStorage.

Esa sesión luego se reusa por test_adres_with_state.py sin intervención.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

URLS = [
    # URL pública informativa (lleva captcha enterprise v3 invisible)
    "https://www.adres.gov.co/consulte-su-eps",
    # URL de consulta directa BDUA (formulario clásico)
    "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
]
OUT = Path(__file__).parent / "_inspect"
STATE_PATH = OUT / "adres_storage_state.json"
META_PATH = OUT / "adres_storage_meta.json"


def capture():
    OUT.mkdir(exist_ok=True)
    print("\n══════════════════════════════════════════════════════════════")
    print("  CAPTURA DE SESIÓN ADRES — Modo manual asistido")
    print("══════════════════════════════════════════════════════════════")
    print("  Se abrirá un navegador. Sigue estos pasos:")
    print("    1. Espera a que cargue el portal ADRES")
    print("    2. Si aparece banner de cookies → Acepta")
    print("    3. Si aparece captcha → Resuélvelo")
    print("    4. Haz UNA consulta de prueba (cualquier cédula real)")
    print("    5. Verifica que devuelva un resultado")
    print("    6. Vuelve aquí y presiona ENTER")
    print("══════════════════════════════════════════════════════════════\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        for url in URLS:
            print(f"  → Abriendo: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                print(f"     OK: {page.url} | título: {page.title()!r}")
            except Exception as e:
                print(f"     fallo: {e}")
            input("\n  Cuando termines este paso, presiona ENTER para continuar...")

        # Guardar estado
        ctx.storage_state(path=str(STATE_PATH))
        cookies = ctx.cookies()
        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "expires_hint_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
            "cookies_count": len(cookies),
            "cookies_domains": sorted(set(c.get("domain", "") for c in cookies)),
            "urls_visited": URLS,
        }
        META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        page.screenshot(path=str(OUT / "adres_session_capturada.png"), full_page=True)
        print(f"\n  ✅ Sesión guardada:")
        print(f"     {STATE_PATH}")
        print(f"     {META_PATH}")
        print(f"     {len(cookies)} cookies de dominios: {meta['cookies_domains']}")
        browser.close()


if __name__ == "__main__":
    capture()
