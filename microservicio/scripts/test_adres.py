"""Test rápido de validación ADRES contra portal real."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.adres_validator import validate_adres

print("=== Test ADRES ===")
result = validate_adres(
    tipo_documento="CC",
    numero_documento="1001911185",
    fecha_inicio="2026-05-01",
    eps_laravel="SANITAS",
)
print(result.model_dump_json(indent=2))
