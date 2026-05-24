"""Test login real EPS Sanitas - empleadores. Verifica si reCAPTCHA es invisible o exige imágenes."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")

USER = os.environ["EPS_SANITAS_USER"]
PASS = os.environ["EPS_SANITAS_PASS"]
URL = os.environ.get("EPS_SANITAS_URL", "https://www.epssanitas.com/usuarios/web/empleadores/inicio")

OUT = Path(__file__).parent / "_inspect"
OUT.mkdir(exist_ok=True)

print(f"[sanitas] Login como {USER}")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    user_sel = "#_autenticacionportlet_WAR_autenticacionempleadoresportlet_screenName"
    pass_sel = "#_autenticacionportlet_WAR_autenticacionempleadoresportlet_password"
    btn_sel = "#_autenticacionportlet_WAR_autenticacionempleadoresportlet_continue-eployee-btn"

    page.fill(user_sel, USER)
    page.fill(pass_sel, PASS)
    page.screenshot(path=str(OUT / "sanitas_01_form_lleno.png"))
    print(f"  Form lleno → {OUT / 'sanitas_01_form_lleno.png'}")

    # Intentar marcar reCAPTCHA v2 checkbox
    try:
        recaptcha_frame = None
        for fr in page.frames:
            if "recaptcha/api2/anchor" in fr.url:
                recaptcha_frame = fr
                break
        if recaptcha_frame:
            print("  Intentando marcar reCAPTCHA checkbox...")
            checkbox = recaptcha_frame.query_selector("#recaptcha-anchor")
            if checkbox:
                checkbox.click()
                page.wait_for_timeout(3000)
                # Verificar si pasó (estado aria-checked)
                checked = recaptcha_frame.get_attribute("#recaptcha-anchor", "aria-checked")
                print(f"  reCAPTCHA aria-checked={checked}")
                page.screenshot(path=str(OUT / "sanitas_02_recaptcha.png"))
    except Exception as e:
        print(f"  reCAPTCHA error: {e}")

    print("\n  >>> Si reCAPTCHA pide imágenes, resuélvelo manualmente en la ventana <<<")
    print("  >>> Después presiona ENTER aquí <<<")
    input()

    page.click(btn_sel)
    page.wait_for_timeout(8000)
    page.wait_for_load_state("networkidle", timeout=30000)

    print(f"  URL post-login: {page.url}")
    page.screenshot(path=str(OUT / "sanitas_03_post_login.png"), full_page=True)
    (OUT / "sanitas_post_login.html").write_text(page.content(), encoding="utf-8")
    print(f"  Screenshot post-login → {OUT / 'sanitas_03_post_login.png'}")

    # Listar enlaces del dashboard
    print("\n  Links del dashboard:")
    links = page.query_selector_all("a[href]")
    seen = set()
    for a in links:
        try:
            href = a.get_attribute("href") or ""
            text = (a.inner_text() or "").strip()[:60]
            if not a.is_visible() or not text:
                continue
            key = (href, text)
            if key in seen:
                continue
            seen.add(key)
            if any(k in href.lower() + text.lower() for k in ("incapac", "radic", "soport", "licencia")):
                print(f"    {text!r} -> {href}")
        except Exception:
            pass

    input("\n  ENTER para cerrar...")
    browser.close()
