"""Registry de adaptadores EPS — patrón Strategy.

Registra automáticamente cada adaptador y permite seleccionarlos
por adapter_key. Facilita agregar nuevas EPS sin tocar código existente.
"""

from __future__ import annotations

from app.adapters.base import EPSAdapter
from app.logger import get_logger

logger = get_logger(__name__)

# Registry global: adapter_key → clase del adaptador
_ADAPTER_REGISTRY: dict[str, type[EPSAdapter]] = {}


def register_adapter(cls: type[EPSAdapter]) -> type[EPSAdapter]:
    """Decorador para registrar un adaptador EPS.

    Uso:
        @register_adapter
        class SanitasAdapter(EPSAdapter):
            adapter_key = "sanitas"
            ...
    """
    key = cls.adapter_key
    if not key:
        raise ValueError(f"Adaptador {cls.__name__} no tiene adapter_key definido")

    _ADAPTER_REGISTRY[key] = cls
    logger.info("adaptador_registrado", adapter_key=key, clase=cls.__name__)
    return cls


def get_adapter(adapter_key: str) -> EPSAdapter:
    """Obtiene una instancia del adaptador para una EPS.

    Args:
        adapter_key: Clave del adaptador (ej: "sanitas", "sura").

    Returns:
        Instancia del adaptador correspondiente.

    Raises:
        ValueError: Si no existe adaptador para esa EPS.
    """
    if adapter_key not in _ADAPTER_REGISTRY:
        available = ", ".join(sorted(_ADAPTER_REGISTRY.keys()))
        raise ValueError(
            f"No hay adaptador registrado para '{adapter_key}'. "
            f"Disponibles: {available or 'ninguno'}"
        )

    adapter_cls = _ADAPTER_REGISTRY[adapter_key]
    return adapter_cls()


def list_adapters() -> dict[str, dict]:
    """Lista todos los adaptadores registrados con su metadata."""
    result = {}
    for key, cls in sorted(_ADAPTER_REGISTRY.items()):
        result[key] = {
            "adapter_key": cls.adapter_key,
            "eps_name": cls.eps_name,
            "max_file_size_kb": cls.max_file_size_kb,
            "supports_radicacion": cls.supports_radicacion,
            "supports_transcripcion": cls.supports_transcripcion,
        }
    return result


def _load_all_adapters() -> None:
    """Importa todos los módulos de adaptadores para que se auto-registren."""
    # Los imports disparan el decorador @register_adapter
    try:
        from app.adapters import sanitas  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import sura  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import salud_total  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import compensar  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import nueva_eps  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import coosalud  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import famisanar  # noqa: F401
    except ImportError:
        pass
    try:
        from app.adapters import mutual_ser  # noqa: F401
    except ImportError:
        pass


# Cargar adaptadores al importar este módulo
_load_all_adapters()
