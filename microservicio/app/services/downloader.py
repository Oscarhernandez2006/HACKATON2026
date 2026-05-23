"""Descargador de archivos desde URLs temporales (S3).

Descarga PDFs, JPGs y PNGs a un directorio temporal aislado por job_uuid.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.config import get_settings
from app.logger import get_logger

logger = get_logger(__name__)

# MIME types soportados
SUPPORTED_MIMES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/jpg",
}


def download_file(url: str, job_uuid: str, filename: str) -> Path:
    """Descarga un archivo desde una URL temporal a disco local.

    Args:
        url: URL temporal (S3 presigned o similar).
        job_uuid: UUID del job para aislar archivos.
        filename: Nombre original del archivo.

    Returns:
        Path al archivo descargado.
    """
    settings = get_settings()
    job_dir = Path(settings.temp_dir) / job_uuid
    job_dir.mkdir(parents=True, exist_ok=True)

    dest = job_dir / filename
    logger.info("descarga_iniciada", url_host=httpx.URL(url).host, filename=filename)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()

    dest.write_bytes(response.content)
    size_kb = len(response.content) / 1024

    logger.info("descarga_completada", filename=filename, size_kb=round(size_kb, 1))
    return dest


def download_adjuntos(adjuntos: list[dict], job_uuid: str) -> list[Path]:
    """Descarga todos los adjuntos de un job.

    Returns:
        Lista de Paths a los archivos descargados.
    """
    paths = []
    for adj in adjuntos:
        mime = adj.get("mime_type", "")
        if mime not in SUPPORTED_MIMES:
            logger.warning("mime_no_soportado", mime=mime, archivo=adj["nombre_original"])
            continue

        path = download_file(
            url=adj["url_temporal"],
            job_uuid=job_uuid,
            filename=adj["nombre_original"],
        )
        paths.append(path)

    if not paths:
        raise ValueError("No se descargó ningún archivo soportado")

    return paths


def cleanup_job_files(job_uuid: str) -> None:
    """Elimina los archivos temporales de un job."""
    import shutil

    settings = get_settings()
    job_dir = Path(settings.temp_dir) / job_uuid
    if job_dir.exists():
        shutil.rmtree(job_dir)
        logger.info("archivos_temporales_eliminados", job_uuid=job_uuid)
