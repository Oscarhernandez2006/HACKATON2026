"""Prueba funcional: extrae datos de PDFs reales con Azure OpenAI Vision."""

import base64
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import dotenv_values
from openai import AzureOpenAI

# ── Config desde .env ──
env = dotenv_values(".env")
AZURE_API_KEY = env.get("AZURE_API_KEY", "")
AI_MODEL = env.get("AI_MODEL", "gpt-chat-latest")
AI_BASE_URL = env.get("AI_BASE_URL", "https://scia.cognitiveservices.azure.com/")
AI_API_VERSION = env.get("AI_API_VERSION", "2024-12-01-preview")


EXTRACTION_PROMPT = """Eres un experto en documentos médicos colombianos de incapacidades laborales.

Analiza la imagen del certificado de incapacidad y extrae los siguientes datos en formato JSON.

CAMPOS A EXTRAER:
- numero_incapacidad: Número o código del certificado
- tipo: Tipo (ENFERMEDAD_GENERAL, ACCIDENTE_TRABAJO, LICENCIA_MATERNIDAD, LICENCIA_PATERNIDAD, ENFERMEDAD_LABORAL)
- origen: COMUN o LABORAL
- fecha_expedicion: Fecha expedición (YYYY-MM-DD)
- fecha_inicio: Fecha inicio incapacidad (YYYY-MM-DD)
- fecha_fin: Fecha fin incapacidad (YYYY-MM-DD)
- dias: Número de días (entero)
- diagnostico_codigo: Código CIE-10 (ej: M545, J060)
- diagnostico_descripcion: Descripción del diagnóstico
- eps_detectada: EPS (SANITAS, SURA, COMPENSAR, NUEVA_EPS, SALUD_TOTAL, COOSALUD, FAMISANAR, MUTUAL_SER)
- medico_nombre: Nombre del médico
- registro_medico: Registro médico / tarjeta profesional
- ips: Nombre de la IPS
- es_prorroga: true/false

REGLAS:
- Si no puedes leer un campo, pon null
- Fechas en YYYY-MM-DD
- Normaliza EPS: "Suramericana"→SURA, "Nueva EPS"→NUEVA_EPS, "Salud Total"→SALUD_TOTAL

Responde SOLO con JSON válido, sin markdown. Estructura:
{
  "extracted_data": { ... },
  "confidence": { "campo": 0.95, ... },
  "needs_review": ["campo1"],
  "notas": "observaciones"
}"""


def pdf_to_base64_images(pdf_path: str) -> list[str]:
    """Convierte PDF a imágenes base64 usando PyMuPDF."""
    doc = fitz.open(pdf_path)
    images = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
        img_bytes = pix.tobytes("png")
        b64 = base64.b64encode(img_bytes).decode()
        images.append(f"data:image/png;base64,{b64}")
        print(f"  📄 Página {page_num + 1} convertida ({len(img_bytes)//1024} KB)")
    doc.close()
    return images


def extract_from_pdf(pdf_path: str) -> dict:
    """Envía el PDF a Azure OpenAI y extrae datos."""
    print(f"\n{'='*60}")
    print(f"📋 Procesando: {Path(pdf_path).name}")
    print(f"{'='*60}")

    # 1. Convertir PDF a imágenes
    print("🔄 Convirtiendo PDF a imágenes...")
    images = pdf_to_base64_images(pdf_path)

    # 2. Construir contenido del mensaje
    content = []
    for data_url in images:
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    content.append({"type": "text", "text": EXTRACTION_PROMPT})

    # 3. Llamar a Azure OpenAI con el SDK oficial
    print(f"🤖 Enviando a {AI_MODEL} (Azure OpenAI)...")
    client = AzureOpenAI(
        api_version=AI_API_VERSION,
        azure_endpoint=AI_BASE_URL,
        api_key=AZURE_API_KEY,
    )

    response = client.chat.completions.create(
        model=AI_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    text = response.choices[0].message.content
    tokens_in = response.usage.prompt_tokens if response.usage else "?"
    tokens_out = response.usage.completion_tokens if response.usage else "?"
    print(f"✅ Respuesta recibida (tokens: {tokens_in} in / {tokens_out} out)")

    # 4. Parsear JSON
    text_clean = text.strip()
    if text_clean.startswith("```"):
        text_clean = text_clean.split("\n", 1)[1]
        text_clean = text_clean.rsplit("```", 1)[0]

    return json.loads(text_clean)


def print_result(data: dict):
    """Imprime los resultados de forma legible."""
    extracted = data.get("extracted_data", {})
    confidence = data.get("confidence", {})
    needs_review = data.get("needs_review", [])
    notas = data.get("notas", "")

    print(f"\n{'─'*40}")
    print("📊 DATOS EXTRAÍDOS:")
    print(f"{'─'*40}")
    for campo, valor in extracted.items():
        conf = confidence.get(campo, "?")
        marker = "⚠️" if campo in needs_review else "✅"
        print(f"  {marker} {campo}: {valor}  (confianza: {conf})")

    if needs_review:
        print(f"\n⚠️  Campos para revisión humana: {', '.join(needs_review)}")
    if notas:
        print(f"\n📝 Notas: {notas}")


if __name__ == "__main__":
    if not AZURE_API_KEY:
        print("❌ AZURE_API_KEY no configurado en .env")
        sys.exit(1)

    # PDFs de prueba (uno por cada EPS)
    test_pdfs = [
        r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SANITAS\JOSE RIVERA INC #1.pdf",
        r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SURA\LUIS CARLOS GARCIA URQUIJO #0.pdf",
        r"..\pluggin\SoportesIncapacidadesReto\CONCURSO\SALUD TOTAL\MELANYS JIMENEZ #1.pdf",
    ]

    print("🚀 PRUEBA FUNCIONAL — Extracción con IA (GPT-4o Vision)")
    print(f"   Modelo: {AI_MODEL}")
    print(f"   Endpoint: {AI_BASE_URL}")
    print(f"   PDFs a procesar: {len(test_pdfs)}")

    resultados = {}
    for pdf in test_pdfs:
        pdf_path = str(Path(pdf).resolve()) if not Path(pdf).is_absolute() else pdf
        try:
            data = extract_from_pdf(pdf_path)
            print_result(data)
            resultados[Path(pdf).name] = data
        except Exception as e:
            print(f"❌ Error procesando {Path(pdf).name}: {e}")

    print(f"\n{'='*60}")
    print(f"🏁 RESUMEN: {len(resultados)}/{len(test_pdfs)} PDFs procesados exitosamente")
    print(f"{'='*60}")

    # Guardar resultados completos
    output_path = "test_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Resultados guardados en {output_path}")
