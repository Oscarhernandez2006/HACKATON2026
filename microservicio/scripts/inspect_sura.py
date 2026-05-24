"""Inspector EPS SURA (empleadores) - lista selectores reales y captura HTML."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")
URL = os.getenv("EPS_SURA_URL")


def inspect():
    out_dir = Path(__file__).parent / "_inspect"
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        print(f"\n[SURA] {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        (out_dir / "sura.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "sura.png"), full_page=True)
        print(f"  URL final: {page.url}")
        print(f"  Title: {page.title()}")

        print("\n  ── INPUTS visibles ──")
        for el in page.query_selector_all("input"):
            try:
                info = el.evaluate("""e => ({
                    id: e.id, name: e.name, type: e.type,
                    placeholder: e.placeholder, value: e.value,
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    input id={info['id']!r} name={info['name']!r} type={info['type']!r} ph={info['placeholder']!r}")
            except Exception:
                pass

        print("\n  ── BUTTONS visibles ──")
        for el in page.query_selector_all("button, input[type=submit]"):
            try:
                info = el.evaluate("""e => ({
                    id: e.id, name: e.name, type: e.type,
                    text: (e.innerText || e.value || '').trim().slice(0, 80),
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    btn id={info['id']!r} name={info['name']!r} text={info['text']!r}")
            except Exception:
                pass

        print("\n  ── SELECT visibles ──")
        for el in page.query_selector_all("select"):
            try:
                info = el.evaluate("""e => ({
                    id: e.id, name: e.name,
                    options: Array.from(e.options).map(o => o.text).slice(0, 8),
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    select id={info['id']!r} name={info['name']!r} opts={info['options']}")
            except Exception:
                pass

        input("\nENTER para cerrar...")
        browser.close()


if __name__ == "__main__":
    inspect()
