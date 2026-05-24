"""Inspector Salud Total (oficina virtual) - selectores reales."""
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")
URL = os.getenv("EPS_SALUD_TOTAL_URL")


def inspect():
    out_dir = Path(__file__).parent / "_inspect"
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        print(f"\n[SALUD TOTAL] {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        (out_dir / "salud_total.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / "salud_total.png"), full_page=True)
        print(f"  URL final: {page.url}")
        print(f"  Title: {page.title()}")

        print("\n  ── INPUTS visibles ──")
        for el in page.query_selector_all("input"):
            try:
                info = el.evaluate("""e => ({
                    id: e.id, name: e.name, type: e.type,
                    placeholder: e.placeholder, ariaLabel: e.getAttribute('aria-label') || '',
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    input id={info['id']!r} name={info['name']!r} type={info['type']!r} ph={info['placeholder']!r} aria={info['ariaLabel']!r}")
            except Exception:
                pass

        print("\n  ── BUTTONS visibles ──")
        for el in page.query_selector_all("button, input[type=submit], a.btn, a[role=button]"):
            try:
                info = el.evaluate("""e => ({
                    id: e.id, name: e.name || '', type: e.type || '',
                    text: (e.innerText || e.value || '').trim().slice(0, 80),
                    visible: e.offsetParent !== null
                })""")
                if info["visible"] and info["text"]:
                    print(f"    btn id={info['id']!r} text={info['text']!r}")
            except Exception:
                pass

        print("\n  ── SELECT / dropdowns ──")
        for el in page.query_selector_all("select, [role=combobox], .k-dropdown, .k-combobox"):
            try:
                info = el.evaluate("""e => ({
                    tag: e.tagName, id: e.id, name: e.name || '',
                    text: (e.innerText || '').trim().slice(0,80),
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    {info['tag']} id={info['id']!r} text={info['text']!r}")
            except Exception:
                pass

        input("\nENTER para cerrar...")
        browser.close()


if __name__ == "__main__":
    inspect()
