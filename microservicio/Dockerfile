FROM python:3.11-slim

# Dependencias del sistema para Tesseract, pdf2image y Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-spa \
    poppler-utils \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar browsers de Playwright
RUN playwright install chromium

# Copiar código
COPY . .

# Crear directorios temporales
RUN mkdir -p /tmp/pdf-a-radicado/evidencias

EXPOSE 8765

# Por defecto arranca la API; en docker-compose se sobreescribe para el worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765"]
