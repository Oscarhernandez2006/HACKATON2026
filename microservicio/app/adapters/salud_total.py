"""Adaptador EPS Salud Total — RPA para portal de incapacidades.

Portal: https://transaccional.saludtotal.com.co/OficinaVirtual/
Límite de archivo: 4 MB (4096 KB)
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
class SaludTotalAdapter(EPSAdapter):
    adapter_key = "salud_total"
    eps_name = "Salud Total"
    max_file_size_kb = 4096
    portal_url = "https://transaccional.saludtotal.com.co/OficinaVirtual/"
    supports_radicacion = True
    supports_transcripcion = False

    async def login(self, credential_ref: str) -> None:
        """Inicia sesión en el portal de Salud Total."""
        from app.services.credential_resolver import resolve_credential

        creds = resolve_credential(credential_ref)

        await self._page.goto(self.portal_url, wait_until="networkidle")
        logger.info("salud_total_portal_cargado")

        # Salud Total usa oficina virtual — login empresa
        await self._page.wait_for_selector(
            'input[name="usuario"], input[id*="usuario"], input[type="text"]',
            timeout=15000,
        )

        # Seleccionar tipo de documento si hay dropdown
        await self._safe_select(
            'select[name*="tipoDoc"], select[id*="tipoDoc"]',
            "NIT",
        )

        await self._safe_fill(
            'input[name="usuario"], input[id*="usuario"], input[type="text"]',
            creds["username"],
        )
        await self._safe_fill(
            'input[name="clave"], input[type="password"]',
            creds["password"],
        )

        await self._page.click(
            'button[type="submit"], input[type="submit"], .btn-ingresar, #btnIngresar'
        )
        await self._page.wait_for_load_state("networkidle")
        logger.info("salud_total_login_exitoso")

    async def eps_radicacion(self, ctx: AdapterContext) -> AdapterResult:
        """Radica una incapacidad en el portal de Salud Total."""
        evidencias = []

        try:
            async with create_isolated_context(ctx.job_uuid) as (browser_ctx, page):
                self._page = page
                self._browser_context = browser_ctx

                # 1. Login
                credential_ref = ctx.radicacion_config.get("credencial_ref", "")
                await self.login(credential_ref)

                # 2. Navegar a módulo de incapacidades
                await self._navigate_to_incapacidades()

                ss = await self.take_screenshot(ctx, "01_post_login")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 3. Llenar datos
                await self._fill_form(ctx)

                ss = await self.take_screenshot(ctx, "02_formulario")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 4. Subir adjuntos
                await self._upload_files(ctx)

                ss = await self.take_screenshot(ctx, "03_adjuntos")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 5. Enviar radicación
                radicado = await self._submit()

                ss = await self.take_screenshot(ctx, "04_confirmacion")
                evidencias.append({"tipo": "comprobante", "path": str(ss)})

                logger.info("salud_total_radicacion_exitosa", radicado=radicado)
                return AdapterResult(
                    success=True,
                    numero_radicado=radicado,
                    mensaje="Radicación exitosa en Salud Total",
                    evidencias=evidencias,
                )

        except Exception as exc:
            logger.exception("salud_total_radicacion_fallida")
            try:
                if self._page:
                    ss_err = await self.take_screenshot(ctx, "error")
                    evidencias.append({"tipo": "screenshot", "path": str(ss_err)})
            except Exception:
                pass

            return AdapterResult(
                success=False,
                mensaje=f"Error en radicación Salud Total: {exc}",
                evidencias=evidencias,
            )

    async def _navigate_to_incapacidades(self) -> None:
        """Navega al módulo de incapacidades en la oficina virtual."""
        selectors = [
            'a:has-text("Incapacidades")',
            'a:has-text("Prestaciones Económicas")',
            'a:has-text("Radicar")',
            '.menu-item:has-text("Incapacidad")',
            'a[href*="incapacidad"]',
            'a[href*="prestacion"]',
        ]
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    await self._page.wait_for_load_state("networkidle")
                    logger.info("salud_total_seccion_incapacidades")
                    return
            except Exception:
                continue

    async def _fill_form(self, ctx: AdapterContext) -> None:
        """Llena el formulario de radicación de Salud Total."""
        inc = ctx.incapacidad
        trab = ctx.trabajador
        emp = ctx.empresa
        medico = ctx.medico

        fields = [
            # Datos del trabajador
            ('input[name*="tipoDoc"], select[name*="tipoDoc"]', trab["tipo_documento"]),
            ('input[name*="numDoc"], input[name*="cedula"]', trab["numero_documento"]),
            ('input[name*="nombre"], input[name*="trabajador"]',
             f'{trab["nombres"]} {trab["apellidos"]}'),
            # Datos de la incapacidad
            ('input[name*="numIncapacidad"], input[name*="consecutivo"]',
             inc.get("numero_incapacidad", "")),
            ('input[name*="fechaInicio"]', inc.get("fecha_inicio", "")),
            ('input[name*="fechaFin"]', inc.get("fecha_fin", "")),
            ('input[name*="dias"]', str(inc.get("dias", ""))),
            ('input[name*="diagnostico"], input[name*="cie"]',
             inc.get("diagnostico_codigo", "")),
            # Datos empresa
            ('input[name*="nit"]', emp.get("numero_identificacion", "")),
            ('input[name*="razonSocial"]', emp.get("razon_social", "")),
            # Datos médico
            ('input[name*="medico"]', medico.get("nombre", "")),
            ('input[name*="registro"]', medico.get("registro_medico", "")),
        ]

        for selector, value in fields:
            await self._safe_fill(selector, value)

        logger.info("salud_total_formulario_llenado")

    async def _upload_files(self, ctx: AdapterContext) -> None:
        """Sube archivos adjuntos al portal."""
        await self.validate_file_sizes(ctx)

        for adjunto_path in ctx.adjuntos_paths:
            try:
                file_input = await self._page.wait_for_selector(
                    'input[type="file"]', timeout=5000
                )
                if file_input:
                    await file_input.set_input_files(str(adjunto_path))
                    await self._page.wait_for_timeout(2000)
                    logger.info("salud_total_archivo_subido", archivo=adjunto_path.name)
            except Exception:
                logger.warning("salud_total_upload_fallido", archivo=adjunto_path.name)

    async def _submit(self) -> str:
        """Envía la radicación y extrae el número de radicado."""
        for selector in [
            'button:has-text("Radicar")',
            'button:has-text("Enviar")',
            'input[type="submit"]',
            'button[type="submit"]',
            '#btnRadicar',
        ]:
            try:
                btn = await self._page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await self._page.wait_for_load_state("networkidle")
        await self._page.wait_for_timeout(3000)
        return await self._extract_radicado()

    async def _extract_radicado(self) -> str:
        """Extrae número de radicado de la página de confirmación."""
        import re

        content = await self._page.content()
        patterns = [
            r"(?:radicado|número|No\.?|consecutivo)\s*[:\-]?\s*([A-Z0-9\-]{6,20})",
            r"(?:RAD|INC|SOL)\s*[\-:]?\s*(\d{6,15})",
            r"(?:exitosa|éxito).*?(\d{8,15})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)

        for selector in [".numero-radicado", "#radicado", ".confirmacion"]:
            try:
                el = await self._page.query_selector(selector)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        return "RADICADO_NO_CAPTURADO"

    # ── Helpers ──

    async def _safe_fill(self, selector: str, value: str) -> None:
        if not value:
            return
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

    async def _safe_select(self, selector: str, value: str) -> None:
        for sel in selector.split(", "):
            try:
                el = await self._page.wait_for_selector(sel.strip(), timeout=3000)
                if el:
                    await el.select_option(value=value)
                    return
            except Exception:
                continue
