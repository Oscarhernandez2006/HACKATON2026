"""Script de inspección: abre ADRES con Playwright y guarda HTML + screenshot."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


URLS = {
    "adres": "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx",
    "rethus": "https://web.sispro.gov.co/THS/Cliente/ConsultasPublicas/ConsultaPublicaDeTHxIdentificacion.aspx",
}


def inspect(name: str, url: str):
    out_dir = Path(__file__).parent / "_inspect"
    out_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"\n[{name}] Cargando {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)  # esperar JS

        html = page.content()
        (out_dir / f"{name}.html").write_text(html, encoding="utf-8")
        page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True)
        print(f"  HTML guardado: {out_dir / f'{name}.html'}")
        print(f"  Screenshot:    {out_dir / f'{name}.png'}")

        inputs = page.query_selector_all("input, select, button, a.btn, [role='button']")
        print(f"\n  {len(inputs)} elementos interactivos:")
        for el in inputs[:40]:
            try:
                tag = el.evaluate("e => e.tagName")
                info = el.evaluate("""e => ({
                    id: e.id || '',
                    name: e.name || '',
                    type: e.type || '',
                    placeholder: e.placeholder || '',
                    text: (e.innerText || '').trim().slice(0, 60),
                    visible: e.offsetParent !== null
                })""")
                if info["visible"]:
                    print(f"    <{tag.lower()}> id={info['id']!r} name={info['name']!r} type={info['type']!r} text={info['text']!r}")
            except Exception:
                pass

        browser.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    if target == "all":
        for k, v in URLS.items():
            inspect(k, v)
    else:
        inspect(target, URLS[target])

