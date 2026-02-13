# Docker образ для OCR Service v2
#
# Единый контейнер: FastAPI + Tesseract + Poppler
# Все зависимости внутри — не требует Python/Tesseract на хосте.
#
# Build:
#   docker build -t tesseract-ocr-service .
#
# Run:
#   docker run -p 8000:8000 --env-file .env tesseract-ocr-service

FROM python:3.11-slim

# Метаданные
LABEL maintainer="tesseract-ocr-service"
LABEL description="OCR Service v2 — распознавание текста из PDF (единый контейнер)"
LABEL version="2.0.0"

# Системные зависимости: Tesseract + Poppler + curl (healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Рабочая директория
WORKDIR /app

# Устанавливаем Python зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем модуль OCR
COPY ocr/ ./ocr/

# Оптимизация CPU: запрет OpenMP внутри worker-процессов
# Без этого каждый Tesseract worker создаст N потоков через OpenMP,
# что при 8 процессах даст 64+ потоков и деградацию
ENV OMP_THREAD_LIMIT=1

# Путь к данным Tesseract (Debian-based python:3.11-slim)
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Переменные окружения читаются из .env через docker-compose (env_file)

# Порт по умолчанию (переопределяется через OCR_PORT в .env)
ENV OCR_PORT=8000

# Запуск сервиса — порт берётся из переменной окружения
CMD uvicorn ocr.main:app --host 0.0.0.0 --port ${OCR_PORT}
