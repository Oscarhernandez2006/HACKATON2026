"""Inspector EPS Sanitas - empleadores. Maneja popups/cookies."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://www.epssanitas.com/usuarios/web/empleadores/inicio"


def inspect():
    out_dir = Path(__file__).parent / "_inspect"
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context()
        page = ctx.new_page()
        print(f"\n[sanitas] Cargando {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # Cerrar cookies/popups si aparecen
        for sel in ["button:has-text('Aceptar')", "button:has-text('Continuar')",
                    "button:has-text('Cerrar')", "[id*='cookie'] button"]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(800)
            except Exception:
                pass

        html = page.content()
        (out_dir / "sanitas.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(out_dir / "sanitas.png"), full_page=True)
        print(f"  HTML: {out_dir / 'sanitas.html'}")
        print(f"  PNG:  {out_dir / 'sanitas.png'}")
        print(f"  URL final: {page.url}")

        inputs = page.query_selector_all("input, select, button, a[href]")
        print(f"\n  Elementos interactivos visibles:")
        seen = set()
        for el in inputs:
            try:
                info = el.evaluate("""e => ({
                    tag: e.tagName.toLowerCase(),
                    id: e.id || '',
                    name: e.name || '',
                    type: e.type || '',
                    placeholder: e.placeholder || '',
                    href: e.href || '',
                    text: (e.innerText || '').trim().slice(0, 80),
                    visible: e.offsetParent !== null
                })""")
                if not info["visible"]:
                    continue
                key = (info["tag"], info["id"], info["name"], info["text"])
                if key in seen:
                    continue
                seen.add(key)
                extra = info["placeholder"] or info["href"][:60] or info["text"]
                print(f"    <{info['tag']}> id={info['id']!r} name={info['name']!r} type={info['type']!r}  {extra!r}")
            except Exception:
                pass

        # Frames
        for fr in page.frames:
            if fr != page.main_frame:
                print(f"\n  IFRAME: {fr.url}")

        input("\nENTER para cerrar...")
        browser.close()


if __name__ == "__main__":
    inspect()
