"""Credential Resolver — resuelve credenciales desde vault o env vars.

En producción se conectaría a HashiCorp Vault, AWS Secrets Manager, etc.
En desarrollo lee de variables de entorno.

IMPORTANTE: Nunca se imprimen credenciales en logs.
"""

from __future__ import annotations

import os

from app.logger import get_logger

logger = get_logger(__name__)


def resolve_credential(credential_ref: str) -> dict[str, str]:
    """Resuelve una referencia de credencial a username/password.

    Formatos soportados:
    - "vault:eps/sanitas" → busca en vault (producción)
    - "env:EPS_SANITAS" → busca en variables de entorno
    - "cred-XXX" → busca por ID en env vars

    En desarrollo, busca las variables de entorno:
    - {PREFIX}_USER
    - {PREFIX}_PASS

    Returns:
        Dict con "username" y "password".
    """
    logger.info("credential_resolve", ref_type=credential_ref.split(":")[0] if ":" in credential_ref else "direct")

    if credential_ref.startswith("vault:"):
        return _resolve_vault(credential_ref)
    elif credential_ref.startswith("env:"):
        return _resolve_env(credential_ref)
    else:
        return _resolve_by_id(credential_ref)


def _resolve_vault(ref: str) -> dict[str, str]:
    """Resuelve credencial desde vault.

    En producción, esto se conectaría a HashiCorp Vault.
    Por ahora, mapea a variables de entorno.
    """
    # vault:eps/sanitas → EPS_SANITAS
    path = ref.replace("vault:", "").replace("/", "_").upper()
    return _get_from_env(path)


def _resolve_env(ref: str) -> dict[str, str]:
    """Resuelve credencial desde variable de entorno directa."""
    prefix = ref.replace("env:", "").upper()
    return _get_from_env(prefix)


def _resolve_by_id(ref: str) -> dict[str, str]:
    """Resuelve credencial por ID genérico."""
    # cred-999 → busca EPS_CRED_999_USER / EPS_CRED_999_PASS
    clean_id = ref.replace("-", "_").upper()
    return _get_from_env(f"EPS_{clean_id}")


def _get_from_env(prefix: str) -> dict[str, str]:
    """Lee username y password de variables de entorno."""
    username = os.environ.get(f"{prefix}_USER", "")
    password = os.environ.get(f"{prefix}_PASS", "")

    if not username or not password:
        raise ValueError(
            f"Credenciales no encontradas para '{prefix}'. "
            f"Configure {prefix}_USER y {prefix}_PASS en las variables de entorno."
        )

    # NUNCA loguear credenciales
    logger.info("credential_resolved", prefix=prefix)
    return {"username": username, "password": password}
