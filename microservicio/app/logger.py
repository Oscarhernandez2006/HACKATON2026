"""Logger estructurado con structlog.

Cada log lleva job_uuid e incapacidad_uuid para trazabilidad.
Las credenciales y tokens se filtran automáticamente.
"""

from __future__ import annotations

import logging
import re
import sys

import structlog


_SENSITIVE_PATTERN = re.compile(
    r"(password|token|secret|credential|bearer|authorization)"
    r"\s*[=:]\s*\S+",
    re.IGNORECASE,
)


def _sanitize_sensitive(_, __, event_dict: dict) -> dict:
    """Remueve credenciales y tokens de los logs."""
    msg = event_dict.get("event", "")
    if isinstance(msg, str):
        event_dict["event"] = _SENSITIVE_PATTERN.sub(r"\1=***REDACTED***", msg)
    return event_dict


def setup_logging(log_level: str = "INFO") -> None:
    """Configura structlog + logging estándar."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            _sanitize_sensitive,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )


def get_logger(name: str = __name__) -> structlog.stdlib.BoundLogger:
    """Retorna un logger con nombre del módulo."""
    return structlog.get_logger(name)


def bind_job_context(job_uuid: str, incapacidad_uuid: str) -> None:
    """Vincula job_uuid e incapacidad_uuid al contexto de logs del hilo actual."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        job_uuid=job_uuid,
        incapacidad_uuid=incapacidad_uuid,
    )
