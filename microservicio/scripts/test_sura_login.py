"""Login real en SURA con credenciales del .env. Captura evidencia."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")

URL = os.getenv("EPS_SURA_URL")
USER = os.getenv("EPS_SURA_USER")
PASS = os.getenv("EPS_SURA_PASS")
TIPO_DOC = "CEDULA"

# Login SSO directo (la URL de empleadores redirige aquí)
SSO_URL = "https://login.sura.com/sso/servicelogin.aspx?continueTo=https%3A%2F%2Fepsapps.suramericana.com%2FSemp%2F&service=epssura"


def login_sura():
    out = Path(__file__).parent / "_inspect"
    out.mkdir(exist_ok=True)
    headless = "--headed" not in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        responses_log = []
        page.on("response", lambda r: responses_log.append((r.status, r.url)) if "login" in r.url.lower() or "sura" in r.url.lower() else None)
        page.on("framenavigated", lambda f: print(f"    [nav] {f.url}") if f == page.main_frame else None)

        print(f"[SURA] Abriendo {URL}")
        # Retry con backoff si chrome-error
        for attempt in range(3):
            try:
                page.goto(URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_selector("#suraName", timeout=20000)
                break
            except Exception as e:
                print(f"  intento {attempt+1} falló: {e}")
                if attempt == 2:
                    raise
                page.wait_for_timeout(3000)
                # intentar URL SSO directa
                try:
                    page.goto(SSO_URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_selector("#suraName", timeout=20000)
                    break
                except Exception:
                    continue
        page.screenshot(path=str(out / "sura_01_login_form.png"), full_page=True)
        print(f"  Tipo: {TIPO_DOC} | User: {USER}")
        page.select_option("#ctl00_ContentMain_suraType", label=TIPO_DOC)
        page.fill("#suraName", USER)
        page.fill("#suraPassword", PASS)
        # Cerrar teclado virtual: blur del password
        page.evaluate("document.getElementById('suraPassword').blur()")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        page.screenshot(path=str(out / "sura_02_filled.png"), full_page=True)

        # Click con force=True bypassea el teclado virtual overlay
        try:
            page.click("#session-internet", force=True, timeout=10000)
        except Exception as e:
            print(f"  click force falló: {e} — intentando JS click")
            page.evaluate("document.getElementById('session-internet').click()")
        print("  Click realizado, esperando respuesta...")
        page.wait_for_timeout(8000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.screenshot(path=str(out / "sura_03_after_login.png"), full_page=True)
        (out / "sura_after_login.html").write_text(page.content(), encoding="utf-8")

        url_after = page.url
        title_after = page.title()
        body_txt = page.evaluate("() => document.body.innerText").lower()
        error_kw = ["incorrecto", "inválid", "no coincide", "error", "verifica"]
        error_found = [kw for kw in error_kw if kw in body_txt]

        print(f"\n  URL despues: {url_after}")
        print(f"  Title: {title_after}")
        if error_found:
            print(f"  ⚠ Posibles errores en página: {error_found}")
        else:
            print(f"  ✓ Sin mensajes de error obvios")

        print(f"\n  Responses SURA/login ({len(responses_log)}):")
        for st, u in responses_log[-15:]:
            print(f"    {st} {u}")

        if "login" not in url_after.lower() or "epsapps" in url_after.lower() and "login" not in url_after.lower():
            print(f"  ✅ LOGIN EXITOSO")
        else:
            print(f"  ❌ Aún en pantalla de login (URL contiene 'login')")

        ctx.storage_state(path=str(out / "sura_storage_state.json"))
        print(f"\n  Storage state guardado: {out / 'sura_storage_state.json'}")
        print(f"  Evidencias en: {out}")
        browser.close()


if __name__ == "__main__":
    login_sura()
