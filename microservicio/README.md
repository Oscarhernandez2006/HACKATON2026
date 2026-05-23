# De PDF a Radicado — Microservicio de Automatización

Microservicio RPA/OCR que automatiza el proceso de incapacidades laborales en Colombia para la plataforma **Incapacidades.ai**.

## ¿Qué hace?

1. **Recibe un PDF/imagen** de incapacidad desde Laravel
2. **Extrae datos con OCR** (Tesseract o AWS Textract): trabajador, fechas, diagnóstico CIE-10, EPS, médico
3. **Valida en ADRES** que el trabajador esté afiliado a la EPS
4. **Valida en RETHUS** que el médico esté registrado y habilitado
5. **Radica automáticamente** en el portal web de la EPS usando RPA (Playwright)
6. **Devuelve resultados** a Laravel con radicado, comprobante y screenshots de evidencia

## Stack

| Componente | Tecnología |
|-----------|-----------|
| API | Python 3.11 + FastAPI |
| Queue | Celery + Redis |
| OCR | Tesseract (local) / AWS Textract (cloud) |
| RPA | Playwright (Chromium headless) |
| HTTP Client | httpx |
| Contenedores | Docker + docker-compose |

## Estructura del proyecto

```
microservicio/
├── app/
│   ├── adapters/              # Adaptadores RPA por EPS
│   │   ├── base.py            # Clase abstracta EPSAdapter
│   │   ├── browser_manager.py # Playwright contexts aislados
│   │   ├── registry.py        # Auto-registro de adaptadores
│   │   ├── sanitas.py         # Adaptador Sanitas (12MB)
│   │   ├── sura.py            # Adaptador Sura (4MB)
│   │   └── salud_total.py     # Adaptador Salud Total (4MB)
│   ├── services/              # Servicios de negocio
│   │   ├── adres_validator.py # Validación ADRES
│   │   ├── callback_manager.py# Callbacks a Laravel
│   │   ├── credential_resolver.py # Resolución de credenciales
│   │   ├── downloader.py      # Descarga de archivos S3
│   │   ├── ocr_engine.py      # Motor OCR dual
│   │   ├── ocr_extractor.py   # Extracción estructurada
│   │   ├── ocr_service.py     # Orquestador OCR
│   │   └── rethus_validator.py# Validación RETHUS
│   ├── auth.py                # Autenticación Bearer
│   ├── config.py              # Configuración centralizada
│   ├── eps_config.py          # Loader config EPS
│   ├── logger.py              # Logger estructurado JSON
│   ├── main.py                # FastAPI app
│   ├── pipeline.py            # Orquestador de pipelines
│   ├── schemas.py             # Modelos Pydantic
│   └── worker.py              # Celery app + tasks
├── tests/                     # Tests unitarios
├── docker-compose.yml         # API + Worker + Redis
├── Dockerfile
├── eps_config.json            # Config de 8 EPS
└── requirements.txt
```

## Inicio rápido

### Con Docker (recomendado)

```bash
# 1. Clonar y entrar al directorio
cd microservicio

# 2. Copiar configuración
cp .env.example .env
# Editar .env con tu INTERNAL_TOKEN y credenciales

# 3. Levantar servicios
docker-compose up --build

# API disponible en http://localhost:8000
# Health check: GET http://localhost:8000/health
```

### Sin Docker (desarrollo local)

```bash
cd microservicio
python -m venv .venv
.venv/Scripts/activate  # Windows
pip install -r requirements.txt
playwright install chromium

# Terminal 1: Redis
# (instalar Redis o usar Docker solo para Redis)

# Terminal 2: API
uvicorn app.main:app --reload --port 8000

# Terminal 3: Worker
celery -A app.worker.celery_app worker --loglevel=info
```

## Endpoints

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| `GET` | `/health` | No | Health check |
| `POST` | `/automation/jobs` | Bearer | Recibe job de Laravel → 202 |
| `GET` | `/automation/jobs/{uuid}/status` | Bearer | Estado del job en Celery |
| `GET` | `/adapters` | Bearer | Lista adaptadores EPS disponibles |

## Tipos de job

### `ocr_adres_rethus`
Descarga el PDF → OCR → valida ADRES → valida RETHUS → callback a Laravel.

```bash
curl -X POST http://localhost:8000/automation/jobs \
  -H "Authorization: Bearer TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d @pluggin/RetoIncapacidadesColombia/RetoIncapacidadesColombia/json/job_ocr_adres_rethus.request.json
```

### `eps_radicacion`
Selecciona adaptador EPS → RPA en portal → captura radicado → callback a Laravel.

```bash
curl -X POST http://localhost:8000/automation/jobs \
  -H "Authorization: Bearer TU_TOKEN" \
  -H "Content-Type: application/json" \
  -d @pluggin/RetoIncapacidadesColombia/RetoIncapacidadesColombia/json/job_radicacion.request.json
```

## Eventos de progreso

El microservicio reporta estos eventos a Laravel via callback:

| Evento | Progreso | Descripción |
|--------|----------|-------------|
| `job_received` | 5% | Job recibido y encolado |
| `ocr_started` | 10% | OCR iniciado |
| `ocr_finished` | 30% | OCR completado |
| `adres_started` | 35% | Validación ADRES iniciada |
| `adres_finished` | 50% | ADRES completada |
| `rethus_started` | 55% | Validación RETHUS iniciada |
| `rethus_finished` | 70% | RETHUS completada |
| `rpa_started` | 75% | RPA en portal EPS iniciado |
| `rpa_finished` | 95% | RPA completado |
| `job_completed` | 100% | Job exitoso |
| `job_failed` | — | Error con detalle |

## Adaptadores EPS disponibles

| EPS | adapter_key | Límite archivo | Radicación | Transcripción |
|-----|-------------|---------------|------------|---------------|
| Sanitas | `sanitas` | 12 MB | ✅ | ❌ |
| Sura | `sura` | 4 MB | ✅ | ✅ |
| Salud Total | `salud_total` | 4 MB | ✅ | ❌ |
| Compensar | `compensar` | 900 KB | 🔜 | 🔜 |
| Nueva EPS | `nueva_eps` | 10 MB | 🔜 | 🔜 |
| Coosalud | `coosalud` | 1.1 MB | 🔜 | 🔜 |
| Famisanar | `famisanar` | 5 MB | 🔜 | 🔜 |
| Mutual Ser | `mutual_ser` | 1 MB | 🔜 | 🔜 |

## Cómo agregar una nueva EPS

1. **Crear archivo** `app/adapters/mi_eps.py`:

```python
from app.adapters.base import AdapterContext, AdapterResult, EPSAdapter
from app.adapters.browser_manager import create_isolated_context
from app.adapters.registry import register_adapter
from app.logger import get_logger

logger = get_logger(__name__)

@register_adapter
class MiEpsAdapter(EPSAdapter):
    adapter_key = "mi_eps"          # Debe coincidir con eps_config.json
    eps_name = "Mi EPS"
    max_file_size_kb = 5120         # Límite en KB
    portal_url = "https://portal.mieps.com"
    supports_radicacion = True
    supports_transcripcion = False

    async def login(self, credential_ref: str):
        from app.services.credential_resolver import resolve_credential
        creds = resolve_credential(credential_ref)
        await self._page.goto(self.portal_url, wait_until="networkidle")
        # ... llenar login ...

    async def eps_radicacion(self, ctx: AdapterContext) -> AdapterResult:
        async with create_isolated_context(ctx.job_uuid) as (browser_ctx, page):
            self._page = page
            await self.login(ctx.radicacion_config["credencial_ref"])
            # ... navegar, llenar formulario, subir archivos ...
            ss = await self.take_screenshot(ctx, "confirmacion")
            return AdapterResult(
                success=True,
                numero_radicado="RAD-XXXXX",
                evidencias=[{"tipo": "comprobante", "path": str(ss)}],
            )
```

2. **Registrar en** `app/adapters/registry.py` — agregar import en `_load_all_adapters()`:

```python
try:
    from app.adapters import mi_eps  # noqa: F401
except ImportError:
    pass
```

3. **Agregar en** `eps_config.json`:

```json
{
  "eps_code": "MI_EPS",
  "name": "Mi EPS",
  "portal_url": "https://portal.mieps.com",
  "max_file_size_kb": 5120,
  "adapter_key": "mi_eps",
  "status": "active",
  "notes": null
}
```

4. **Configurar credenciales** en `.env`:

```
EPS_MI_EPS_USER=usuario
EPS_MI_EPS_PASS=contraseña
```

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `INTERNAL_TOKEN` | Token Bearer para autenticación | Requerido |
| `REDIS_URL` | URL de Redis | `redis://localhost:6379/0` |
| `OCR_ENGINE` | Motor OCR: `tesseract` o `textract` | `tesseract` |
| `CALLBACK_ALLOWED_HOSTS` | Hosts permitidos para callbacks | `localhost` |
| `PLAYWRIGHT_HEADLESS` | Navegador sin ventana | `true` |
| `CELERY_WORKER_CONCURRENCY` | Workers paralelos | `4` |
| `MAX_BROWSER_CONTEXTS` | Navegadores simultáneos | `4` |

Ver `.env.example` para la lista completa.

## Seguridad

- Comunicación con Bearer token obligatorio
- Callback URL validada contra allowlist
- Firma HMAC-SHA256 opcional en callbacks
- Credenciales resueltas desde vault/env vars, nunca en logs
- Sesiones de navegador aisladas por job
- Sin conexión directa a base de datos de Laravel

## Tests

```bash
cd microservicio
pip install pytest pytest-asyncio
pytest tests/ -v
```
