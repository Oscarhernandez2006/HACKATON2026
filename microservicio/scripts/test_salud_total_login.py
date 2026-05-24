"""Login real Salud Total — pestaña EMPLEADORES (4 campos)."""
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv(Path(__file__).parent.parent / ".env")

URL = os.getenv("EPS_SALUD_TOTAL_URL")
USER_RAW = os.getenv("EPS_SALUD_TOTAL_USER", "")
PASS = os.getenv("EPS_SALUD_TOTAL_PASS")

# .env: "NIT 901240743 - CC 1001911185"  → empleador y usuario
pairs = re.findall(r"(NIT|CC|CE|TI|PT)\s+([\dA-Z]+)", USER_RAW, re.I)
if len(pairs) < 2:
    raise SystemExit(f"EPS_SALUD_TOTAL_USER mal formado: {USER_RAW!r} (espero 'NIT xxx - CC yyy')")
EMP_TIPO, EMP_NUM = pairs[0][0].upper(), pairs[0][1]
USR_TIPO, USR_NUM = pairs[1][0].upper(), pairs[1][1]
# El dropdown muestra "CEDULA DE CIUDADANIA" no "CC", mapeamos por substring:
TIPO_MAP = {
    "CC": "CEDULA DE CIUDADANIA",
    "NIT": "NIT",
    "CE": "CEDULA DE EXTRANJERIA",
    "TI": "TARJETA DE IDENTIDAD",
    "PT": "PERMISO POR PROTECCION TEMPORAL",
    "PA": "PASAPORTE",
}


def pick_kendo(page, input_el, label_substring: str):
    # Kendo combobox filtrable: escribir texto → el listbox aparece filtrado
    input_el.click()
    page.wait_for_timeout(300)
    input_el.fill("")
    input_el.type(label_substring, delay=50)
    page.wait_for_timeout(900)
    # Buscar opciones del popup (Kendo usa ul.k-list con li.k-item)
    opts = page.query_selector_all("ul.k-list li.k-item, li[role='option']")
    for o in opts:
        try:
            if not o.is_visible():
                continue
            txt = (o.inner_text() or "").upper().strip()
            if label_substring.upper() in txt:
                o.click()
                page.wait_for_timeout(400)
                return txt
        except Exception:
            pass
    # fallback: ArrowDown + Enter
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(200)
    page.keyboard.press("Enter")
    page.wait_for_timeout(400)
    return f"(fallback Enter on {label_substring})"


def login():
    out = Path(__file__).parent / "_inspect"
    out.mkdir(exist_ok=True)
    headless = "--headed" not in sys.argv

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()
        print(f"[SALUD_TOTAL] {URL}")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        page.screenshot(path=str(out / "salud_total_01_form.png"), full_page=True)

        print("  Activando pestaña EMPLEADORES...")
        tab = page.query_selector("li[role='tab']:has-text('EMPLEADORES')")
        if not tab:
            print("  ❌ Pestaña EMPLEADORES no encontrada")
            return
        tab.click()
        page.wait_for_timeout(2000)
        page.wait_for_selector("input[placeholder='NÚMERO DE DOCUMENTO DEL EMPLEADOR']", timeout=20000)
        page.screenshot(path=str(out / "salud_total_02_tab_empleadores.png"), full_page=True)

        print(f"  Empleador: {EMP_TIPO} {EMP_NUM} | Usuario: {USR_TIPO} {USR_NUM}")

        emp_tipo_in = page.query_selector("input[placeholder='TIPO DE DOCUMENTO DEL EMPLEADOR']")
        if emp_tipo_in:
            sel = pick_kendo(page, emp_tipo_in, TIPO_MAP.get(EMP_TIPO, EMP_TIPO))
            print(f"    Empleador tipo: {sel}")

        page.fill("input[placeholder='NÚMERO DE DOCUMENTO DEL EMPLEADOR']", EMP_NUM)

        usr_tipo_in = page.query_selector("input[placeholder='TIPO DE DOCUMENTO DEL USUARIO']")
        if usr_tipo_in:
            sel = pick_kendo(page, usr_tipo_in, TIPO_MAP.get(USR_TIPO, USR_TIPO))
            print(f"    Usuario tipo: {sel}")

        page.fill("input[placeholder='NÚMERO DE DOCUMENTO DEL USUARIO']", USR_NUM)
        page.fill("input[placeholder='CONTRASEÑA']", PASS)

        chk = page.query_selector("input[type=checkbox]")
        if chk and chk.is_visible():
            try:
                chk.check()
            except Exception:
                pass

        page.screenshot(path=str(out / "salud_total_03_filled.png"), full_page=True)

        print("  Click INGRESAR...")
        page.click("button:has-text('INGRESAR')")
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(6000)
        page.screenshot(path=str(out / "salud_total_04_after.png"), full_page=True)
        (out / "salud_total_after.html").write_text(page.content(), encoding="utf-8")

        url_after = page.url
        body_txt = page.evaluate("() => document.body.innerText").lower()
        error_kw = ["incorrecto", "inválid", "no coincide", "datos erróneos", "credenciales", "usuario o contraseña"]
        error_found = [kw for kw in error_kw if kw in body_txt]

        print(f"\n  URL después: {url_after}")
        print(f"  Title: {page.title()}")
        if error_found:
            print(f"  ⚠ Errores detectados: {error_found}")
        if "#/" in url_after and len(url_after.split("#/", 1)[1]) > 1:
            print(f"  ✅ Posible login exitoso (cambió ruta SPA)")
        else:
            print(f"  ❌ Sigue en home")

        ctx.storage_state(path=str(out / "salud_total_storage_state.json"))
        print(f"\n  Storage state: {out / 'salud_total_storage_state.json'}")
        browser.close()


if __name__ == "__main__":
    login()
