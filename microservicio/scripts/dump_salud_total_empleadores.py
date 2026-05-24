"""Inspect Salud Total EMPLEADORES tab to see real fields."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")
URL = os.getenv("EPS_SALUD_TOTAL_URL")


def run():
    out = Path(__file__).parent / "_inspect"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)

        # Listar todas las pestañas
        tabs = page.query_selector_all("li[role='tab']")
        print(f"Pestañas encontradas ({len(tabs)}):")
        for t in tabs:
            print(f"  - {t.inner_text().strip()!r}  active={t.get_attribute('aria-selected')}")

        # Click EMPLEADORES
        tab = page.query_selector("li[role='tab']:has-text('EMPLEADORES')")
        if tab:
            tab.click()
            page.wait_for_timeout(2000)
            print("\n[EMPLEADORES tab activa]")

        page.screenshot(path=str(out / "salud_total_empleadores_tab.png"), full_page=True)
        (out / "salud_total_empleadores.html").write_text(page.content(), encoding="utf-8")

        print("\nINPUTS visibles en pestaña EMPLEADORES:")
        for el in page.query_selector_all("input"):
            try:
                i = el.evaluate("""e => ({
                    id: e.id, name: e.name, type: e.type,
                    ph: e.placeholder, aria: e.getAttribute('aria-label') || '',
                    visible: e.offsetParent !== null
                })""")
                if i["visible"]:
                    print(f"  input id={i['id']!r} name={i['name']!r} type={i['type']!r} ph={i['ph']!r} aria={i['aria']!r}")
            except Exception:
                pass

        print("\nBUTTONS visibles:")
        for el in page.query_selector_all("button"):
            try:
                b = el.evaluate("""e => ({
                    id: e.id, text: (e.innerText||'').trim().slice(0,60),
                    visible: e.offsetParent !== null
                })""")
                if b["visible"] and b["text"]:
                    print(f"  btn id={b['id']!r} text={b['text']!r}")
            except Exception:
                pass

        browser.close()


if __name__ == "__main__":
    run()
