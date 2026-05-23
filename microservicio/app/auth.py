"""Autenticación Bearer token para comunicación Laravel ↔ Microservicio."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

_bearer_scheme = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    """Valida que el Bearer token coincida con INTERNAL_TOKEN.

    Retorna el token si es válido; lanza 401 si no.
    """
    if credentials.credentials != settings.internal_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )
    return credentials.credentials
