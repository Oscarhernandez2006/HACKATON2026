"""Browser Manager — gestiona instancias Playwright aisladas por job.

Garantiza:
- Un browser context por job (aislamiento de sesiones)
- Límite máximo de contextos concurrentes
- Cleanup automático al finalizar
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)

# Semáforo global para limitar contextos de navegador concurrentes
_semaphore: asyncio.Semaphore | None = None
_browser: Browser | None = None
_playwright_instance = None


def _get_semaphore() -> asyncio.Semaphore:
    """Obtiene o crea el semáforo de concurrencia."""
    global _semaphore
    if _semaphore is None:
        settings = get_settings()
        _semaphore = asyncio.Semaphore(settings.max_browser_contexts)
    return _semaphore


async def _get_browser() -> Browser:
    """Obtiene o lanza la instancia global del browser."""
    global _browser, _playwright_instance

    if _browser is None or not _browser.is_connected():
        settings = get_settings()
        _playwright_instance = await async_playwright().start()
        _browser = await _playwright_instance.chromium.launch(
            headless=settings.playwright_headless,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        logger.info("browser_lanzado", headless=settings.playwright_headless)

    return _browser


@asynccontextmanager
async def create_isolated_context(
    job_uuid: str,
) -> AsyncGenerator[tuple[BrowserContext, Page], None]:
    """Crea un contexto de navegador aislado para un job.

    Usa semáforo para limitar concurrencia.
    El contexto se cierra automáticamente al salir del bloque.

    Yields:
        Tupla (BrowserContext, Page) lista para usar.
    """
    settings = get_settings()
    sem = _get_semaphore()

    logger.info("browser_context_solicitado", job_uuid=job_uuid)
    async with sem:
        browser = await _get_browser()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="es-CO",
            timezone_id="America/Bogota",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        context.set_default_timeout(settings.playwright_timeout)

        page = await context.new_page()
        logger.info("browser_context_creado", job_uuid=job_uuid)

        try:
            yield context, page
        finally:
            await page.close()
            await context.close()
            logger.info("browser_context_cerrado", job_uuid=job_uuid)


async def shutdown_browser() -> None:
    """Cierra la instancia global del browser (para shutdown del servicio)."""
    global _browser, _playwright_instance

    if _browser:
        await _browser.close()
        _browser = None
    if _playwright_instance:
        await _playwright_instance.stop()
        _playwright_instance = None
    logger.info("browser_global_cerrado")
