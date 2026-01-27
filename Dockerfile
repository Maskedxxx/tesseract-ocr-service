# Docker образ для OCR API
#
# Содержит только API слой (без Tesseract).
# Проксирует запросы к OCR Worker, запущенному на хосте.
#
# Build:
#   docker build -t tesseract-ocr-service-api .
#
# Run:
#   docker run -p 8000:8000 tesseract-ocr-service-api

FROM python:3.11-slim

# Метаданные
LABEL maintainer="tesseract-ocr-service"
LABEL description="OCR Service API - проксирование к OCR Worker"
LABEL version="1.0.0"

# Рабочая директория
WORKDIR /app

# Устанавливаем зависимости API (без Tesseract и pdf2image)
RUN pip install --no-cache-dir \
    fastapi==0.109.0 \
    uvicorn==0.27.0 \
    httpx==0.26.0 \
    python-multipart==0.0.6 \
    pydantic==2.5.3 \
    pydantic-settings==2.1.0

# Копируем только app/ (API слой)
COPY app/ ./app/

# Порт API
EXPOSE 8000

# Переменные окружения по умолчанию
ENV OCR_WORKER_URL=http://host.docker.internal:8001
ENV OCR_MAX_FILE_SIZE_MB=100
ENV OCR_TIMEOUT_SECONDS=300

# Запуск API
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
