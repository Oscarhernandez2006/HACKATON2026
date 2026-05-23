"""Prueba funcional: extrae datos de PDFs reales con PyMuPDF + regex."""
import sys
import json
from pathlib import Path

# Agregar el directorio del proyecto al path
sys.path.insert(0, str(Path(__file__).parent))

import fitz

# Importar el extractor regex
from app.services.ocr_extractor import extract_structured_data

test_pdfs = [
    r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SANITAS\JOSE RIVERA INC #1.pdf",
    r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SURA\LUIS CARLOS GARCIA URQUIJO #0.pdf",
    r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SALUD TOTAL\MELANYS JIMENEZ #1.pdf",
]

print("PRUEBA FUNCIONAL - Extraccion PDF -> Texto -> Datos Estructurados")
print(f"PDFs a procesar: {len(test_pdfs)}\n")

resultados = {}
for pdf in test_pdfs:
    path = Path(pdf).resolve()
    print(f"{'='*60}")
    print(f"PDF: {path.name}")
    print(f"{'='*60}")

    # 1. Extraer texto con PyMuPDF
    doc = fitz.open(str(path))
    full_text = ""
    for i in range(len(doc)):
        full_text += doc[i].get_text() + "\n"
    doc.close()
    print(f"Texto extraido: {len(full_text)} caracteres")

    # 2. Aplicar regex para extraer campos
    result = extract_structured_data(full_text)

    # 3. Mostrar resultados
    data_dict = result.data.model_dump(exclude_none=True)
    print(f"\nDATOS EXTRAIDOS ({len(data_dict)} campos):")
    print(f"{'-'*40}")
    for campo, valor in data_dict.items():
        conf = result.confidence.get(campo, "?")
        marker = "!!" if campo in result.needs_review else "OK"
        print(f"  [{marker}] {campo}: {valor}  (conf: {conf})")

    if result.needs_review:
        print(f"\n  Campos para revision: {', '.join(result.needs_review)}")

    resultados[path.name] = {
        "extracted_data": data_dict,
        "confidence": result.confidence,
        "needs_review": result.needs_review,
    }
    print()

print(f"{'='*60}")
print(f"RESUMEN: {len(resultados)}/{len(test_pdfs)} PDFs procesados")
print(f"{'='*60}")

with open("test_results.json", "w", encoding="utf-8") as f:
    json.dump(resultados, f, ensure_ascii=False, indent=2, default=str)
print(f"\nResultados guardados en test_results.json")
