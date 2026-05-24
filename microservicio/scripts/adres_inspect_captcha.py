"""Inspecciona el captcha del BDUA ADRES: sitekey, tipo, action."""
from pathlib import Path
from playwright.sync_api import sync_playwright

STATE = Path(__file__).parent / "_inspect" / "adres_storage_state.json"
URL = "https://aplicaciones.adres.gov.co/BDUA_Internet/Pages/ConsultarAfiliadoWeb_2.aspx"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(storage_state=str(STATE)) if STATE.exists() else browser.new_context()
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle", timeout=30000)

    # Buscar iframes de recaptcha
    print("\n── IFRAMES ──")
    for f in page.frames:
        if "recaptcha" in f.url or "captcha" in f.url:
            print(f"  {f.url}")

    # Buscar divs g-recaptcha
    print("\n── ELEMENTOS g-recaptcha ──")
    for el in page.query_selector_all("div.g-recaptcha, [data-sitekey]"):
        print(f"  tag={el.evaluate('e => e.tagName')} sitekey={el.get_attribute('data-sitekey')} "
              f"size={el.get_attribute('data-size')} version={el.get_attribute('data-version')}")

    # Buscar scripts recaptcha
    print("\n── SCRIPTS recaptcha ──")
    for s in page.query_selector_all("script[src*='recaptcha']"):
        print(f"  {s.get_attribute('src')}")

    # Buscar textarea g-recaptcha-response (v2 normal)
    print("\n── textarea response ──")
    for t in page.query_selector_all("textarea[name*='recaptcha'], textarea#g-recaptcha-response"):
        print(f"  name={t.get_attribute('name')} id={t.get_attribute('id')}")

    # Form action
    print("\n── FORMS ──")
    for f in page.query_selector_all("form"):
        print(f"  action={f.get_attribute('action')} method={f.get_attribute('method')} id={f.get_attribute('id')}")

    # IDs de campos del formulario
    print("\n── CAMPOS ──")
    for sel in ["#tipoDoc", "#txtNumDoc", "#btnConsultar", "select", "input[type='text']", "input[type='submit']", "button"]:
        for el in page.query_selector_all(sel):
            txt = (el.inner_text() or "").strip()[:30]
            print(f"  {sel} → id={el.get_attribute('id')} name={el.get_attribute('name')} text='{txt}'")

    page.screenshot(path=str(Path(__file__).parent / "_inspect" / "adres_captcha_inspect.png"), full_page=True)
    browser.close()
