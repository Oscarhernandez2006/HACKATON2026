"""Lista opciones del dropdown USUARIO cuando se escribe."""
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
            el.click()
            page.wait_for_timeout(400)
            # Click la flechita para abrir todas
            arrow = el.evaluate_handle("e => e.closest('kendo-combobox').querySelector('.k-select')")
            try:
                arrow.as_element().click()
            except Exception:
                pass
            page.wait_for_timeout(800)
            opts = page.query_selector_all("ul.k-list li.k-item")
            print(f"  total opciones visibles: {len(opts)}")
            for o in opts:
                try:
                    if not o.is_visible(): continue
                    t = (o.inner_text() or "").strip()
                    print(f"    {t!r}")
                except Exception:
                    pass
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)
        browser.close()


if __name__ == "__main__":
    run()
