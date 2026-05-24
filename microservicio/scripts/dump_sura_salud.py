"""Captura selectores REALES de SURA y Salud Total (no-interactivo)."""
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")

TARGETS = {
    "sura": os.getenv("EPS_SURA_URL"),
    "salud_total": os.getenv("EPS_SALUD_TOTAL_URL"),
}


def dump(name: str, url: str, out_dir: Path):
    print(f"\n========== {name.upper()} ==========")
    print(f"URL: {url}")
    result = {"name": name, "url": url, "inputs": [], "buttons": [], "selects": [], "frames": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)
        except Exception as e:
            print(f"  navegación: {e}")

        (out_dir / f"{name}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True)
        result["final_url"] = page.url
        result["title"] = page.title()
        print(f"  Final URL: {page.url}")
        print(f"  Title: {page.title()}")

        for el in page.query_selector_all("input"):
            try:
                i = el.evaluate("""e => ({
                    id: e.id, name: e.name, type: e.type,
                    ph: e.placeholder, aria: e.getAttribute('aria-label') || '',
                    cls: e.className || '',
                    visible: e.offsetParent !== null
                })""")
                if i["visible"]:
                    result["inputs"].append(i)
            except Exception:
                pass

        for el in page.query_selector_all("button, input[type=submit], a.btn, a[role=button]"):
            try:
                b = el.evaluate("""e => ({
                    tag: e.tagName, id: e.id, name: e.name || '', type: e.type || '',
                    text: (e.innerText || e.value || '').trim().slice(0,80),
                    cls: e.className || '',
                    visible: e.offsetParent !== null
                })""")
                if b["visible"] and b["text"]:
                    result["buttons"].append(b)
            except Exception:
                pass

        for el in page.query_selector_all("select, [role=combobox]"):
            try:
                s = el.evaluate("""e => ({
                    tag: e.tagName, id: e.id, name: e.name || '',
                    text: (e.innerText||'').trim().slice(0,80),
                    visible: e.offsetParent !== null
                })""")
                if s["visible"]:
                    result["selects"].append(s)
            except Exception:
                pass

        for fr in page.frames:
            if fr != page.main_frame:
                result["frames"].append(fr.url)

        browser.close()

    print(f"\n  INPUTS ({len(result['inputs'])}):")
    for i in result["inputs"][:20]:
        print(f"    id={i['id']!r} name={i['name']!r} type={i['type']!r} ph={i['ph']!r} aria={i['aria']!r}")
    print(f"\n  BUTTONS ({len(result['buttons'])}):")
    for b in result["buttons"][:15]:
        print(f"    id={b['id']!r} text={b['text']!r}")
    print(f"\n  SELECTS ({len(result['selects'])}):")
    for s in result["selects"][:10]:
        print(f"    id={s['id']!r} text={s['text']!r}")
    if result["frames"]:
        print(f"\n  IFRAMES: {result['frames']}")

    return result


def main():
    out_dir = Path(__file__).parent / "_inspect"
    out_dir.mkdir(exist_ok=True)
    all_results = {}
    for name, url in TARGETS.items():
        try:
            all_results[name] = dump(name, url, out_dir)
        except Exception as e:
            print(f"[{name}] ERROR: {e}")
    (out_dir / "sura_salud_selectors.json").write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n\nGuardado: {out_dir / 'sura_salud_selectors.json'}")


if __name__ == "__main__":
    main()
