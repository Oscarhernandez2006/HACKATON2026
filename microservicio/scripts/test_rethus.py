"""Test RETHUS contra portal real con DR. ANDRES FELIPE TIJO (PDF SANITAS)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.rethus_validator import validate_rethus

print("=== Test RETHUS ===")
result = validate_rethus(
    registro_medico="1019093117",
    medico_nombre="DR. ANDRES FELIPE TIJO",
    tipo_documento="CC",
)
print(result.model_dump_json(indent=2))
