"""Escáner de portales EPS: detecta reCAPTCHA y form fields para decidir viabilidad."""
import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

EPS = {
    "sura":        os.environ["EPS_SURA_URL"],
    "sanitas":     os.environ["EPS_SANITAS_URL"],
    "mutual_ser":  os.environ["EPS_MUTUAL_SER_URL"],
    "salud_total": os.environ["EPS_SALUD_TOTAL_URL"],
    "compensar":   os.environ["EPS_COMPENSAR_URL"],
    "colmena":     os.environ["EPS_COLMENA_URL"],
}

OUT = Path(__file__).parent / "_inspect"
OUT.mkdir(exist_ok=True)


def scan(name: str, url: str) -> dict:
    info = {"eps": name, "url": url, "ok": False, "captcha": "none", "fields": [], "error": None}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(6000)

            html = page.content().lower()
            # Detectar tipo de captcha
            if "recaptcha/enterprise" in html or "grecaptcha.enterprise" in html:
                info["captcha"] = "recaptcha-enterprise"
            elif "recaptcha/api2" in html or "g-recaptcha" in html or "grecaptcha" in html:
                info["captcha"] = "recaptcha-v2"
            elif "hcaptcha" in html:
                info["captcha"] = "hcaptcha"
            elif "captchaimage.ashx" in html or 'id="imgcaptcha"' in html:
                info["captcha"] = "image-aspnet"
            elif "cloudflare" in html and "challenge" in html:
                info["captcha"] = "cloudflare"

            # Capturar inputs y botones de login
            inputs = page.query_selector_all("input, button[type='submit'], button:has-text('Ingresar'), button:has-text('Iniciar')")
            for el in inputs[:25]:
                try:
                    d = el.evaluate("""e => ({
                        tag: e.tagName.toLowerCase(),
                        id: e.id || '',
                        name: e.name || '',
                        type: e.type || '',
                        placeholder: e.placeholder || '',
                        text: (e.innerText || '').trim().slice(0, 40),
                        visible: e.offsetParent !== null
                    })""")
                    if d["visible"] and (d["type"] in ("text", "password", "email", "submit") or d["tag"] == "button"):
                        info["fields"].append(d)
                except Exception:
                    pass

            page.screenshot(path=str(OUT / f"eps_{name}.png"), full_page=False)
            info["ok"] = True
            info["final_url"] = page.url
            browser.close()
    except Exception as e:
        info["error"] = str(e)[:200]
    return info


if __name__ == "__main__":
    print(f"{'EPS':<14} {'CAPTCHA':<22} {'PASS/USER FIELDS':<40}  URL")
    print("-" * 130)
    results = []
    for name, url in EPS.items():
        r = scan(name, url)
        results.append(r)
        if r["error"]:
            print(f"{name:<14} ERROR: {r['error']}")
            continue
        # Resumir fields con password o text
        fields_summary = []
        for f in r["fields"]:
            if f["type"] == "password":
                fields_summary.append(f"PASS({f['id'] or f['name']})")
            elif f["type"] in ("text", "email"):
                ident = (f["id"] or f["name"] or f["placeholder"])[:20]
                fields_summary.append(f"USR({ident})")
        captcha_icon = {
            "none": "✓ SIN CAPTCHA",
            "recaptcha-v2": "⚠ reCAPTCHA v2",
            "recaptcha-enterprise": "✗ reCAPTCHA Ent",
            "hcaptcha": "⚠ hCaptcha",
            "image-aspnet": "✓ Captcha imagen",
            "cloudflare": "✗ Cloudflare",
        }[r["captcha"]]
        print(f"{name:<14} {captcha_icon:<22} {' '.join(fields_summary)[:38]:<40}  {url[:60]}")

    print("\n=== RESUMEN ===")
    sin_captcha = [r["eps"] for r in results if r["captcha"] in ("none", "image-aspnet") and not r["error"]]
    print(f"Viables sin reCAPTCHA: {sin_captcha}")
