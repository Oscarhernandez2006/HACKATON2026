"""Clase base abstracta para adaptadores EPS.

Cada EPS tiene un adaptador que hereda de esta clase.
Define la interfaz común para:
- solicitud_transcripcion: registrar incapacidad en portal EPS
- eps_radicacion: radicar incapacidad ya validada

Cada adaptador gestiona su propia sesión de Playwright aislada.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AdapterResult:
    """Resultado de una operación RPA en portal EPS."""
    success: bool
    numero_radicado: str | None = None
    numero_solicitud: str | None = None
    mensaje: str = ""
    evidencias: list[dict] = field(default_factory=list)
    # dict con {"tipo": "screenshot"|"comprobante", "path": str}


@dataclass
class AdapterContext:
    """Contexto que recibe cada adaptador para ejecutar."""
    job_uuid: str
    incapacidad_uuid: str
    empresa: dict
    trabajador: dict
    incapacidad: dict
    medico: dict
    adjuntos_paths: list[Path]  # Archivos ya descargados localmente
    radicacion_config: dict
    evidence_dir: Path


class EPSAdapter(abc.ABC):
    """Interfaz base para todos los adaptadores EPS.

    Cada adaptador concreto implementa al menos uno de los dos flujos:
    - solicitud_transcripcion
    - eps_radicacion
    """

    # ── Metadata del adaptador (cada subclase define) ──
    adapter_key: str = ""
    eps_name: str = ""
    max_file_size_kb: int = 0
    portal_url: str = ""

    # Flujos soportados por este adaptador
    supports_transcripcion: bool = False
    supports_radicacion: bool = False

    def __init__(self) -> None:
        self._browser_context = None
        self._page = None

    # ── Métodos abstractos ──

    @abc.abstractmethod
    async def login(self, credential_ref: str) -> None:
        """Inicia sesión en el portal de la EPS.

        Args:
            credential_ref: Referencia a la credencial (vault:eps/xxx).
        """
        ...

    @abc.abstractmethod
    async def eps_radicacion(self, ctx: AdapterContext) -> AdapterResult:
        """Radica una incapacidad en el portal de la EPS.

        Args:
            ctx: Contexto con todos los datos necesarios.

        Returns:
            AdapterResult con radicado, evidencias, etc.
        """
        ...

    # ── Métodos opcionales (override si la EPS lo soporta) ──

    async def solicitud_transcripcion(self, ctx: AdapterContext) -> AdapterResult:
        """Solicita transcripción de incapacidad (si la EPS lo requiere)."""
        raise NotImplementedError(
            f"Adaptador {self.adapter_key} no soporta solicitud_transcripcion"
        )

    # ── Helpers comunes ──

    async def take_screenshot(self, ctx: AdapterContext, name: str) -> Path:
        """Captura screenshot del estado actual del navegador."""
        if self._page is None:
            raise RuntimeError("No hay página activa para screenshot")

        filename = f"{ctx.job_uuid}_{self.adapter_key}_{name}.png"
        path = ctx.evidence_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path), full_page=True)

        logger.info("screenshot_capturado", archivo=filename)
        return path

    async def validate_file_sizes(self, ctx: AdapterContext) -> None:
        """Valida que los archivos adjuntos no excedan el límite de la EPS."""
        for path in ctx.adjuntos_paths:
            size_kb = path.stat().st_size / 1024
            if size_kb > self.max_file_size_kb:
                raise ValueError(
                    f"Archivo '{path.name}' ({size_kb:.0f} KB) excede el límite "
                    f"de {self.max_file_size_kb} KB para {self.eps_name}"
                )

    async def cleanup(self) -> None:
        """Cierra el contexto del navegador."""
        if self._page:
            await self._page.close()
            self._page = None
        if self._browser_context:
            await self._browser_context.close()
            self._browser_context = None
        logger.info("browser_context_cerrado", adapter=self.adapter_key)
