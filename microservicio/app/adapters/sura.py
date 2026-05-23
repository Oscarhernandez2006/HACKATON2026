"""Adaptador EPS Sura — RPA para portal de incapacidades.

Portal: https://epsapps.suramericana.com
Límite de archivo: 4 MB (4096 KB)
Flujos soportados: eps_radicacion, solicitud_transcripcion
"""

from __future__ import annotations

from pathlib import Path

from app.adapters.base import AdapterContext, AdapterResult, EPSAdapter
from app.adapters.browser_manager import create_isolated_context
from app.adapters.registry import register_adapter
from app.logger import get_logger

logger = get_logger(__name__)


@register_adapter
class SuraAdapter(EPSAdapter):
    adapter_key = "sura"
    eps_name = "EPS Sura"
    max_file_size_kb = 4096
    portal_url = "https://epsapps.suramericana.com"
    supports_radicacion = True
    supports_transcripcion = True

    async def login(self, credential_ref: str) -> None:
        """Inicia sesión en el portal de Sura."""
        from app.services.credential_resolver import resolve_credential

        creds = resolve_credential(credential_ref)

        await self._page.goto(self.portal_url, wait_until="networkidle")
        logger.info("sura_portal_cargado")

        # Login Sura — típicamente usa usuario empresa + contraseña
        await self._page.wait_for_selector(
            'input[name="username"], input[name="usuario"], input[type="text"]',
            timeout=15000,
        )
        await self._page.fill(
            'input[name="username"], input[name="usuario"], input[type="text"]',
            creds["username"],
        )
        await self._page.fill(
            'input[name="password"], input[type="password"]',
            creds["password"],
        )
        await self._page.click('button[type="submit"], .btn-ingresar, #btnIngresar')
        await self._page.wait_for_load_state("networkidle")
        logger.info("sura_login_exitoso")

    async def eps_radicacion(self, ctx: AdapterContext) -> AdapterResult:
        """Radica una incapacidad en el portal de Sura."""
        evidencias = []

        try:
            async with create_isolated_context(ctx.job_uuid) as (browser_ctx, page):
                self._page = page
                self._browser_context = browser_ctx

                # 1. Login
                credential_ref = ctx.radicacion_config.get("credencial_ref", "")
                await self.login(credential_ref)

                # 2. Navegar a radicación
                await self._navigate_to_radicacion()

                ss = await self.take_screenshot(ctx, "01_post_login")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 3. Llenar formulario
                await self._fill_form(ctx)

                ss = await self.take_screenshot(ctx, "02_formulario")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 4. Subir adjuntos
                await self._upload_files(ctx)

                ss = await self.take_screenshot(ctx, "03_adjuntos")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # 5. Enviar
                radicado = await self._submit(ctx)

                ss = await self.take_screenshot(ctx, "04_confirmacion")
                evidencias.append({"tipo": "comprobante", "path": str(ss)})

                logger.info("sura_radicacion_exitosa", radicado=radicado)
                return AdapterResult(
                    success=True,
                    numero_radicado=radicado,
                    mensaje="Radicación exitosa en Sura",
                    evidencias=evidencias,
                )

        except Exception as exc:
            logger.exception("sura_radicacion_fallida")
            try:
                if self._page:
                    ss_err = await self.take_screenshot(ctx, "error")
                    evidencias.append({"tipo": "screenshot", "path": str(ss_err)})
            except Exception:
                pass

            return AdapterResult(
                success=False,
                mensaje=f"Error en radicación Sura: {exc}",
                evidencias=evidencias,
            )

    async def solicitud_transcripcion(self, ctx: AdapterContext) -> AdapterResult:
        """Solicita transcripción de incapacidad en Sura."""
        evidencias = []

        try:
            async with create_isolated_context(ctx.job_uuid) as (browser_ctx, page):
                self._page = page
                self._browser_context = browser_ctx

                credential_ref = ctx.radicacion_config.get("credencial_ref", "")
                await self.login(credential_ref)

                # Navegar a sección de transcripción
                await self._navigate_to_transcripcion()

                ss = await self.take_screenshot(ctx, "01_transcripcion")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # Llenar datos del trabajador y la incapacidad
                await self._fill_transcripcion_form(ctx)

                # Subir soporte
                await self._upload_files(ctx)

                ss = await self.take_screenshot(ctx, "02_transcripcion_form")
                evidencias.append({"tipo": "screenshot", "path": str(ss)})

                # Enviar solicitud
                numero_solicitud = await self._submit_transcripcion()

                ss = await self.take_screenshot(ctx, "03_transcripcion_confirm")
                evidencias.append({"tipo": "comprobante", "path": str(ss)})

                logger.info("sura_transcripcion_exitosa", solicitud=numero_solicitud)
                return AdapterResult(
                    success=True,
                    numero_solicitud=numero_solicitud,
                    mensaje="Solicitud de transcripción exitosa en Sura",
                    evidencias=evidencias,
                )

        except Exception as exc:
            logger.exception("sura_transcripcion_fallida")
            return AdapterResult(
                success=False,
                mensaje=f"Error en transcripción Sura: {exc}",
                evidencias=evidencias,
            )

    # ── Navegación ──

    async def _navigate_to_radicacion(self) -> None:
        """Navega a la sección de radicación de incapacidades."""
        selectors = [
            'a:has-text("Incapacidades")',
            'a:has-text("Prestaciones")',
            'a[href*="incapacidad"]',
            'a[href*="prestaciones"]',
        ]
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    await self._page.wait_for_load_state("networkidle")
                    return
            except Exception:
                continue

    async def _navigate_to_transcripcion(self) -> None:
        """Navega a la sección de transcripción."""
        selectors = [
            'a:has-text("Transcripción")',
            'a:has-text("Solicitud")',
            'a[href*="transcripcion"]',
        ]
        for selector in selectors:
            try:
                el = await self._page.wait_for_selector(selector, timeout=5000)
                if el:
                    await el.click()
                    await self._page.wait_for_load_state("networkidle")
                    return
            except Exception:
                continue

    # ── Formularios ──

    async def _fill_form(self, ctx: AdapterContext) -> None:
        """Llena formulario de radicación Sura."""
        inc = ctx.incapacidad
        trab = ctx.trabajador
        emp = ctx.empresa

        fields = [
            ('input[name*="tipoDoc"], #tipoDocumento', trab["tipo_documento"]),
            ('input[name*="documento"], #documento', trab["numero_documento"]),
            ('input[name*="incapacidad"], #numIncapacidad', inc.get("numero_incapacidad", "")),
            ('input[name*="fechaInicio"], #fechaInicio', inc.get("fecha_inicio", "")),
            ('input[name*="fechaFin"], #fechaFin', inc.get("fecha_fin", "")),
            ('input[name*="dias"], #dias', str(inc.get("dias", ""))),
            ('input[name*="diagnostico"], #diagnostico', inc.get("diagnostico_codigo", "")),
            ('input[name*="nit"], #nit', emp.get("numero_identificacion", "")),
        ]

        for selector, value in fields:
            await self._safe_fill(selector, value)

        logger.info("sura_formulario_llenado")

    async def _fill_transcripcion_form(self, ctx: AdapterContext) -> None:
        """Llena formulario de transcripción Sura."""
        inc = ctx.incapacidad
        trab = ctx.trabajador
        medico = ctx.medico

        fields = [
            ('input[name*="documento"], #documento', trab["numero_documento"]),
            ('input[name*="incapacidad"]', inc.get("numero_incapacidad", "")),
            ('input[name*="medico"], #medico', medico.get("nombre", "")),
            ('input[name*="registro"], #registro', medico.get("registro_medico", "")),
        ]

        for selector, value in fields:
            await self._safe_fill(selector, value)

    # ── Upload y submit ──

    async def _upload_files(self, ctx: AdapterContext) -> None:
        """Sube archivos adjuntos."""
        await self.validate_file_sizes(ctx)

        for adjunto_path in ctx.adjuntos_paths:
            try:
                file_input = await self._page.wait_for_selector(
                    'input[type="file"]', timeout=5000
                )
                if file_input:
                    await file_input.set_input_files(str(adjunto_path))
                    await self._page.wait_for_timeout(2000)
                    logger.info("sura_archivo_subido", archivo=adjunto_path.name)
            except Exception:
                logger.warning("sura_upload_no_encontrado", archivo=adjunto_path.name)

    async def _submit(self, ctx: AdapterContext) -> str:
        """Envía radicación y extrae radicado."""
        for selector in ['button:has-text("Radicar")', 'button:has-text("Enviar")', 'button[type="submit"]']:
            try:
                btn = await self._page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await self._page.wait_for_load_state("networkidle")
        await self._page.wait_for_timeout(3000)
        return await self._extract_number()

    async def _submit_transcripcion(self) -> str:
        """Envía solicitud de transcripción y extrae número."""
        for selector in ['button:has-text("Solicitar")', 'button:has-text("Enviar")', 'button[type="submit"]']:
            try:
                btn = await self._page.wait_for_selector(selector, timeout=5000)
                if btn:
                    await btn.click()
                    break
            except Exception:
                continue

        await self._page.wait_for_load_state("networkidle")
        await self._page.wait_for_timeout(3000)
        return await self._extract_number()

    async def _extract_number(self) -> str:
        """Extrae número de radicado o solicitud de la página."""
        import re

        content = await self._page.content()
        patterns = [
            r"(?:radicado|solicitud|número|No\.?)\s*[:\-]?\s*([A-Z0-9\-]{6,20})",
            r"(?:RAD|SOL|INC)\s*[\-:]?\s*(\d{6,15})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        return "NUMERO_NO_CAPTURADO"

    async def _safe_fill(self, selector: str, value: str) -> None:
        """Llena un campo de forma segura."""
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
