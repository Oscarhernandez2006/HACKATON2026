"""Carga la configuración de EPS desde el JSON oficial del reto."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EPSConfig:
    eps_code: str
    name: str
    portal_url: str
    max_file_size_kb: int
    adapter_key: str
    status: str
    notes: str | None = None


_EPS_REGISTRY: dict[str, EPSConfig] = {}


def load_eps_configs(config_path: str | Path | None = None) -> dict[str, EPSConfig]:
    """Carga las configuraciones de EPS desde el archivo JSON.

    Si no se pasa path, busca en la ubicación por defecto del repo.
    """
    global _EPS_REGISTRY

    if _EPS_REGISTRY:
        return _EPS_REGISTRY

    if config_path is None:
        # Buscar en la raíz del proyecto
        base = Path(__file__).resolve().parent.parent
        candidates = [
            base / "eps_config.json",
            base.parent / "pluggin" / "RetoIncapacidadesColombia"
            / "RetoIncapacidadesColombia" / "03_EPS_CONFIG.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None:
        raise FileNotFoundError("No se encontró el archivo de configuración de EPS")

    path = Path(config_path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    for entry in raw:
        cfg = EPSConfig(
            eps_code=entry["eps_code"],
            name=entry["name"],
            portal_url=entry["portal_url"],
            max_file_size_kb=entry["max_file_size_kb"],
            adapter_key=entry["adapter_key"],
            status=entry["status"],
            notes=entry.get("notes"),
        )
        _EPS_REGISTRY[cfg.adapter_key] = cfg

    return _EPS_REGISTRY


def get_eps_config(adapter_key: str) -> EPSConfig:
    """Obtiene la config de una EPS por adapter_key."""
    registry = load_eps_configs()
    if adapter_key not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(f"EPS '{adapter_key}' no encontrada. Disponibles: {available}")
    return registry[adapter_key]


def validate_file_size(adapter_key: str, file_size_kb: int) -> bool:
    """Valida que el archivo no exceda el límite de la EPS."""
    cfg = get_eps_config(adapter_key)
    return file_size_kb <= cfg.max_file_size_kb
