# OCR Service

Инкапсулированный stateless OCR-сервис для распознавания текста из PDF документов.

## Архитектура

```
┌────────────────────┐         ┌─────────────────────────────────────┐
│   Docker API       │         │      OCR Worker (вне Docker)        │
│   (:8000)          │  HTTP   │      (:8001)                        │
│                    │ ──────► │                                     │
│ - принимает PDF    │         │ - PDF → images (split)              │
│ - валидация        │         │ - OSD + rotation (ориентация)       │
│ - проксирование    │         │ - deskew (наклон)                   │
│ - возврат JSON     │         │ - Tesseract OCR (параллельно)       │
└────────────────────┘         └─────────────────────────────────────┘
```

**Почему Worker вне Docker?**
- Tesseract OCR использует все ядра CPU
- ProcessPoolExecutor работает эффективнее на хосте
- Не нужно тяжёлый образ с Tesseract внутри Docker

## Деплой

### 1. Системные зависимости

```bash
# macOS
brew install poppler tesseract tesseract-lang

# Ubuntu/Debian
sudo apt update
sudo apt install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng poppler-utils

# Проверка установки
tesseract --version    # Tesseract 5.x.x
pdftoppm -v            # poppler-utils
```

### 2. Python окружение

```bash
# Клонировать репозиторий
git clone <repo-url> /opt/ocr-service
cd /opt/ocr-service

# Сделать скрипты исполняемыми (если права сбросились)
chmod +x start.sh stop.sh

# Создать виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Установить зависимости
pip install -r requirements.txt
```

### 3. Конфигурация

```bash
cp .env.example .env
nano .env  # редактировать под своё окружение
```

Ключевые параметры:

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `OCR_PORT` | Порт API | 8000 |
| `OCR_WORKER_PORT` | Порт Worker | 8001 |
| `OCR_WORKER_URL` | URL Worker для API | http://localhost:8001 |
| `OCR_MAX_FILE_SIZE_MB` | Макс. размер PDF | 100 |
| `OCR_TIMEOUT_SECONDS` | Таймаут обработки | 300 |

### 4. Запуск

```bash
# Запуск всего стека (Worker + Docker API)
./start.sh

# Или локальный режим без Docker
./start.sh --local

# Остановка
./stop.sh
```

Скрипт автоматически:
- ✅ Проверяет зависимости (python, tesseract, poppler)
- ✅ Запускает OCR Worker в фоне
- ✅ Ждёт готовности Worker
- ✅ Запускает Docker API (или локальный)

### 5. Запуск через systemd (продакшн)

Создать `/etc/systemd/system/ocr-worker.service`:

```ini
[Unit]
Description=OCR Worker Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/ocr-service
Environment="PATH=/opt/ocr-service/venv/bin"
ExecStart=/opt/ocr-service/venv/bin/python -m ocr_worker.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ocr-worker
sudo systemctl start ocr-worker
```

### 6. Проверка

```bash
# Health check
curl http://localhost:8001/health   # Worker
curl http://localhost:8000/health   # API

# Тест OCR
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@document.pdf"

# С параметрами
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@document.pdf" \
  -F 'config={"languages":["rus","eng"],"pages":[1,2,3]}'
```

## API Endpoints

### `GET /health`

Проверка работоспособности API и Worker.

```json
{
  "status": "ok",
  "service": "ocr-api",
  "worker": {
    "url": "http://host.docker.internal:8001",
    "status": "ok",
    "info": {...}
  }
}
```

### `POST /ocr/execute`

Распознавание текста из PDF.

**Параметры:**
- `file` (required): PDF файл
- `config` (optional): JSON конфигурация

**Конфигурация:**
```json
{
  "languages": ["rus"],           // Языки: rus, eng, rus+eng
  "pages": [1, 3, 5],             // Конкретные страницы
  "page_start": 1,                // Или диапазон: с
  "page_end": 10                  // по
}
```

**Приоритет выбора страниц:**
1. `pages` — конкретный список
2. `page_start`/`page_end` — диапазон
3. Все страницы если ничего не указано

**Ответ:**
```json
{
  "success": true,
  "total_pages": 5,
  "processing_time_ms": 12500,
  "pages": [
    {
      "page_number": 1,
      "text": "Распознанный текст...",
      "confidence": 87.5,
      "rotation_applied": 90,
      "deskew_angle": 0.5,
      "width": 2480,
      "height": 3508,
      "processing_time_ms": 2100
    }
  ],
  "config_used": {
    "languages": ["rus", "eng"],
    "pages": null,
    "page_start": null,
    "page_end": null
  },
  "file_info": {
    "filename": "document.pdf",
    "size_bytes": 1234567
  }
}
```

## Конфигурация

Все настройки задаются в файле `.env`. Скопируйте шаблон и настройте:

```bash
cp .env.example .env
```

Подробная документация по каждому параметру — в `.env.example`.

### API (префикс `OCR_`)

| Переменная | Описание |
|------------|----------|
| `OCR_WORKER_URL` | URL OCR Worker |
| `OCR_MAX_FILE_SIZE_MB` | Макс. размер PDF в МБ |
| `OCR_TIMEOUT_SECONDS` | Таймаут ожидания Worker |

### Worker (префикс `OCR_WORKER_`)

| Параметр | Описание |
|----------|----------|
| **Split** | |
| `OCR_WORKER_RENDER_DPI` | DPI рендеринга PDF |
| `OCR_WORKER_RENDER_THREAD_COUNT` | Потоков pdftoppm |
| **OSD** | |
| `OCR_WORKER_OSD_CROP_PERCENT` | Кроп краёв (0.15 = 70% центр) |
| `OCR_WORKER_OSD_RESIZE_PX` | Размер для OSD |
| `OCR_WORKER_OSD_CONFIDENCE_THRESHOLD` | Мин. уверенность для поворота |
| **Deskew** | |
| `OCR_WORKER_DESKEW_RESIZE_PX` | Размер для deskew |
| `OCR_WORKER_DESKEW_NUM_PEAKS` | Пики для алгоритма |
| `OCR_WORKER_SKEW_THRESHOLD` | Мин. угол коррекции (градусы) |
| **OCR** | |
| `OCR_WORKER_OCR_OEM` | Engine mode (3 = LSTM + Legacy) |
| `OCR_WORKER_OCR_PSM` | Page segmentation (6 = uniform block) |

## Структура проекта

```
tesseract_docker/
├── .env                          # Конфигурация (из .env.example)
├── .env.example                  # Шаблон конфигурации с документацией
├── app/                          # Docker API
│   ├── __init__.py
│   ├── main.py                   # POST /ocr/execute, GET /health
│   ├── config.py                 # Лимиты, URL воркера
│   └── schemas.py                # OCRConfig, OCRResponse
│
├── ocr_worker/                   # Локальный Worker
│   ├── __init__.py
│   ├── main.py                   # FastAPI app (:8001)
│   ├── config.py                 # Внутренние параметры
│   ├── schemas.py                # PageResult, OCRResult
│   │
│   └── services/
│       ├── __init__.py
│       ├── pdf_processor.py      # split_pdf_to_images
│       ├── osd_worker.py         # process_osd, apply_rotation
│       ├── skew_worker.py        # process_skew, apply_deskew
│       └── ocr_processor.py      # process_ocr, process_document
│
├── Dockerfile                    # Образ API (без Tesseract)
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Пайплайн обработки

```
PDF файл
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Split: PDF → images                                     │
│     • pdftoppm (C++, многопоточный)                         │
│     • DPI=300, JPEG                                         │
│     • 8 потоков параллельно                                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  2. OSD: определение ориентации                             │
│     • Crop 70% центр (убирает шум сканера)                  │
│     • Resize 2048px                                         │
│     • Tesseract --psm 0                                     │
│     • ProcessPoolExecutor (N ядер CPU)                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Rotation: применение поворота                           │
│     • 0°, 90°, 180°, 270°                                   │
│     • PIL.Image.transpose (без потерь)                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Deskew: коррекция наклона                               │
│     • Resize 1200px                                         │
│     • Алгоритм проекционного профиля                        │
│     • num_peaks=20                                          │
│     • Порог: >0.3°                                          │
│     • ProcessPoolExecutor (N ядер CPU)                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  5. OCR: распознавание текста                               │
│     • Tesseract --oem 3 --psm 6                             │
│     • Языки: rus, eng, rus+eng                              │
│     • ProcessPoolExecutor (N ядер CPU)                      │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
JSON с текстом и метаданными
```

## Тестирование

```bash
# Health check
curl http://localhost:8000/health

# Простой тест
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@test.pdf" | jq .

# Проверить Worker напрямую
curl http://localhost:8001/health
```
