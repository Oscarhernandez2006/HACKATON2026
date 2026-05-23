"""Adaptador EPS Sanitas — RPA para portal de incapacidades.

Portal: https://www.epssanitas.com/usuarios/web/nuevo-portal-eps/incapacidades-y-licencias1
Límite de archivo: 12 MB (12288 KB)
Flujos soportados: eps_radicacion
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.base import AdapterContext, AdapterResult, EPSAdapter
from app.adapters.browser_manager import create_isolated_context
from app.adapters.registry import register_adapter
from app.logger import get_logger

logger = get_logger(__name__)


@register_adapter
class SanitasAdapter(EPSAdapter):
    adapter_key = "sanitas"
    eps_name = "EPS Sanitas"
    max_file_size_kb = 12288
    portal_url = "https://www.epssanitas.com/usuarios/web/nuevo-portal-eps/incapacidades-y-licencias1"
    supports_radicacion = True
    supports_transcripcion = False

    async def login(self, credential_ref: str) -> None:
        """Inicia sesión en el portal de Sanitas."""
        from app.services.credential_resolver import resolve_credential

        creds = resolve_credential(credential_ref)

        await self._page.goto(self.portal_url, wait_until="networkidle")
        logger.info("sanitas_portal_cargado")

        # Esperar y llenar formulario de login
        await self._page.wait_for_selector('input[name="usuario"], input[type="text"]', timeout=15000)
        await self._page.fill('input[name="usuario"], input[type="text"]', creds["username"])
        await self._page.fill('input[name="contrasena"], input[type="password"]', creds["password"])
        await self._page.click('button[type="submit"], .btn-login, #btnLogin')

        # Esperar que cargue el dashboard
        await self._page.wait_for_load_state("networkidle")
        logger.info("sanitas_login_exitoso")

    async def eps_radicacion(self, ctx: AdapterContext) -> AdapterResult:
        """Radica una incapacidad en el portal de Sanitas."""
        evidencias = []

        try:
            async with create_isolated_context(ctx.job_uuid) as (browser_ctx, page):
                self._page = page
                self._browser_context = browser_ctx

                # 1. Login
                credential_ref = ctx.radicacion_config.get("credencial_ref", "")
                await self.login(credential_ref)

                # 2. Navegar a sección de incapacidades
                await self._navigate_to_incapacidades()

                # Screenshot post-login
                ss_login = await self.take_screenshot(ctx, "01_post_login")
                evidencias.append({"tipo": "screenshot", "path": str(ss_login)})

                # 3. Llenar formulario de radicación
                await self._fill_radicacion_form(ctx)

                # Screenshot formulario lleno
                ss_form = await self.take_screenshot(ctx, "02_formulario_lleno")
                evidencias.append({"tipo": "screenshot", "path": str(ss_form)})

                # 4. Subir archivos adjuntos
                await self._upload_adjuntos(ctx)

                # Screenshot archivos subidos
                ss_upload = await self.take_screenshot(ctx, "03_archivos_subidos")
                evidencias.append({"tipo": "screenshot", "path": str(ss_upload)})

                # 5. Enviar radicación
                numero_radicado = await self._submit_radicacion()

                # Screenshot confirmación
                ss_confirm = await self.take_screenshot(ctx, "04_confirmacion")
                evidencias.append({"tipo": "comprobante", "path": str(ss_confirm)})

                logger.info("sanitas_radicacion_exitosa", radicado=numero_radicado)

                return AdapterResult(
                    success=True,
                    numero_radicado=numero_radicado,
                    mensaje="Radicación exitosa en Sanitas",
                    evidencias=evidencias,
                )

        except Exception as exc:
            logger.exception("sanitas_radicacion_fallida")

            # Intentar screenshot de error
            try:
                if self._page:
                    ss_err = await self.take_screenshot(ctx, "error")
                    evidencias.append({"tipo": "screenshot", "path": str(ss_err)})
            except Exception:
                pass

            return AdapterResult(
                success=False,
                mensaje=f"Error en radicación Sanitas: {exc}",
                evidencias=evidencias,
            )

    async def _navigate_to_incapacidades(self) -> None:
        """Navega a la sección de radicación de incapacidades."""
        # Buscar link/botón de incapacidades en el menú
        selectors = [
            'a:has-text("Incapacidades")',
            'a:has-text("Radicar")',
            'a[href*="incapacidad"]',
            '.menu-incapacidades',
        ]
        for selector in selectors:
            try:
                element = await self._page.wait_for_selector(selector, timeout=5000)
                if element:
                    await element.click()
                    await self._page.wait_for_load_state("networkidle")
                    logger.info("sanitas_seccion_incapacidades")
                    return
            except Exception:
                continue

        # Si no encuentra menú, intentar navegar directo
        await self._page.goto(
            "https://www.epssanitas.com/usuarios/web/nuevo-portal-eps/incapacidades-y-licencias1",
            wait_until="networkidle",
        )

    async def _fill_radicacion_form(self, ctx: AdapterContext) -> None:
        """Llena el formulario de radicación con datos de la incapacidad."""
        inc = ctx.incapacidad
        trabajador = ctx.trabajador
        empresa = ctx.empresa

        # Tipo de documento del trabajador
        await self._safe_select_or_fill(
            'select[name*="tipoDoc"], #tipoDocumento',
            trabajador["tipo_documento"],
        )

        # Número de documento
        await self._safe_fill(
            'input[name*="numDoc"], input[name*="documento"], #numeroDocumento',
            trabajador["numero_documento"],
        )

        # Número de incapacidad
        await self._safe_fill(
            'input[name*="numIncapacidad"], input[name*="numero"], #numeroIncapacidad',
            inc.get("numero_incapacidad", ""),
        )

        # Fecha inicio
        await self._safe_fill(
            'input[name*="fechaInicio"], input[type="date"], #fechaInicio',
            inc.get("fecha_inicio", ""),
        )

        # Fecha fin
        await self._safe_fill(
            'input[name*="fechaFin"], #fechaFin',
            inc.get("fecha_fin", ""),
        )

        # Días
        await self._safe_fill(
            'input[name*="dias"], #dias',
            str(inc.get("dias", "")),
        )

        # Diagnóstico CIE-10
        await self._safe_fill(
            'input[name*="diagnostico"], input[name*="cie"], #diagnostico',
            inc.get("diagnostico_codigo", ""),
        )

        # NIT empresa
        await self._safe_fill(
            'input[name*="nit"], input[name*="empresa"], #nitEmpresa',
            empresa.get("numero_identificacion", ""),
        )

        logger.info("sanitas_formulario_llenado")

    async def _upload_adjuntos(self, ctx: AdapterContext) -> None:
        """Sube los archivos adjuntos al portal."""
        # Validar tamaños antes de subir
        await self.validate_file_sizes(ctx)

        file_input_selectors = [
            'input[type="file"]',
            '#fileUpload',
            'input[name*="archivo"]',
            'input[accept*="pdf"]',
        ]

        for adjunto_path in ctx.adjuntos_paths:
            for selector in file_input_selectors:
                try:
                    file_input = await self._page.wait_for_selector(selector, timeout=5000)
                    if file_input:
                        await file_input.set_input_files(str(adjunto_path))
                        await self._page.wait_for_timeout(2000)
                        logger.info("sanitas_archivo_subido", archivo=adjunto_path.name)
                        break
                except Exception:
                    continue

    async def _submit_radicacion(self) -> str:
        """Envía el formulario y captura el número de radicado."""
        submit_selectors = [
            'button[type="submit"]',
            'button:has-text("Radicar")',
            'button:has-text("Enviar")',
            '#btnRadicar',
            '.btn-submit',
        ]

        for selector in submit_selectors:
            try:
                btn = await self._page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        # Esperar respuesta del portal
        await self._page.wait_for_load_state("networkidle")
        await self._page.wait_for_timeout(3000)

        # Intentar extraer número de radicado de la página de confirmación
        radicado = await self._extract_radicado()
        return radicado

    async def _extract_radicado(self) -> str:
        """Extrae el número de radicado de la página de confirmación."""
        import re

        content = await self._page.content()

        # Patrones comunes de radicado en portales EPS
        patterns = [
            r"(?:radicado|número|No\.?)\s*[:\-]?\s*([A-Z0-9\-]{6,20})",
            r"(?:RAD|INC|SOL)\s*[\-:]?\s*(\d{6,15})",
            r"(?:exitosa|confirmación).*?(\d{8,15})",
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)

        # Fallback: buscar en elementos de la página
        for selector in [".numero-radicado", "#radicado", ".confirmacion-numero"]:
            try:
                element = await self._page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        return "RADICADO_NO_CAPTURADO"

    # ── Helpers privados ──

    async def _safe_fill(self, selector: str, value: str) -> None:
        """Intenta llenar un campo; no falla si no lo encuentra."""
        if not value:
            return
        for sel in selector.split(", "):
            try:
                el = await self._page.wait_for_selector(sel.strip(), timeout=3000)
                if el:
                    await el.fill(value)
                    return
            except Exception:
                continue

    async def _safe_select_or_fill(self, selector: str, value: str) -> None:
        """Intenta seleccionar de un dropdown o llenar como texto."""
        for sel in selector.split(", "):
            try:
                el = await self._page.wait_for_selector(sel.strip(), timeout=3000)
                if el:
                    tag = await el.evaluate("el => el.tagName")
                    if tag == "SELECT":
                        await el.select_option(value=value)
                    else:
                        await el.fill(value)
                    return
            except Exception:
                continue
