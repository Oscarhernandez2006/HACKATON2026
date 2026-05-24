"""Lista opciones del dropdown TIPO DE DOCUMENTO DEL EMPLEADOR."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")
URL = os.getenv("EPS_SALUD_TOTAL_URL")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)
        tab = page.query_selector("li[role='tab']:has-text('EMPLEADORES')")
        tab.click()
        page.wait_for_timeout(2000)

        for ph in ["TIPO DE DOCUMENTO DEL EMPLEADOR", "TIPO DE DOCUMENTO DEL USUARIO"]:
            print(f"\n=== {ph} ===")
            el = page.query_selector(f"input[placeholder='{ph}']")
            if not el:
                print("  no encontrado"); continue
            el.click()
            page.wait_for_timeout(700)
            # Dump TODOS los li/option visibles que aparecen
            opts = page.query_selector_all("li, [role='option']")
            seen = set()
            for o in opts:
                try:
                    if not o.is_visible(): continue
                    t = (o.inner_text() or "").strip()
                    if not t or t in seen: continue
                    seen.add(t)
                    role = o.get_attribute("role") or ""
                    cls = (o.get_attribute("class") or "")[:60]
                    print(f"  <li role={role!r} class={cls!r}>  {t!r}")
                except Exception:
                    pass
            # cerrar dropdown
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        browser.close()


if __name__ == "__main__":
    run()
