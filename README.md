# OCR Service v2

Распознавание текста из PDF документов. Один Docker-контейнер со всеми зависимостями — не требует Python, Tesseract или Poppler на хосте.

## Быстрый старт

```bash
# 1. Конфигурация
cp .env.example .env
nano .env                        # указать свободный порт в OCR_PORT

# 2. Запуск
docker-compose up --build -d

# 3. Проверка
curl http://localhost:8000/health

# 4. Распознать PDF
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@document.pdf"
```

## Конфигурация

Все настройки в файле `.env`. Подробное описание каждого параметра — в `.env.example`.

| Переменная | Что делает | По умолчанию |
|---|---|---|
| `OCR_PORT` | Порт сервиса | `8000` |
| `OCR_MAX_FILE_SIZE_MB` | Макс. размер PDF | `100` |
| `OCR_RENDER_DPI` | DPI рендеринга | `300` |
| `OCR_RENDER_THREAD_COUNT` | Потоки pdftoppm | `8` |
| `OCR_OCR_OEM` | Tesseract engine mode | `3` |
| `OCR_OCR_PSM` | Page segmentation mode | `6` |

Смена порта — одна переменная:
```bash
OCR_PORT=9090
```

## API

### `POST /ocr/execute` — распознать PDF

```bash
# Простой вызов (язык: rus, все страницы)
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@document.pdf"

# С параметрами
curl -X POST http://localhost:8000/ocr/execute \
  -F "file=@document.pdf" \
  -F 'config={"languages":["rus","eng"], "pages":[1,2,3]}'
```

**Параметры config:**

| Поле | Тип | Описание |
|---|---|---|
| `languages` | `["rus"]` | Языки OCR: `rus`, `eng`, `["rus","eng"]` |
| `pages` | `[1,3,5]` | Конкретные страницы |
| `page_start` | `1` | Начало диапазона |
| `page_end` | `10` | Конец диапазона |

Приоритет: `pages` > `page_start/page_end` > все страницы.

**Ответ:**

```json
{
  "success": true,
  "doc_id": "uuid-для-координат",
  "total_pages": 3,
  "processing_time_ms": 8500,
  "pages": [
    {
      "page_number": 1,
      "text": "Распознанный текст...",
      "confidence": 87.5,
      "rotation_applied": 0,
      "deskew_angle": 0.3,
      "width": 2480,
      "height": 3508
    }
  ],
  "config_used": {"languages": ["rus"], ...},
  "file_info": {"filename": "document.pdf", "size_bytes": 1234567}
}
```

### `GET /health` — статус сервиса

```bash
curl http://localhost:8000/health
```

Возвращает: версию Tesseract, кол-во CPU, текущий конфиг.

### `GET /documents/{doc_id}/coordinates` — координаты слов

Для подсветки текста на фронтенде. `doc_id` берётся из ответа `/ocr/execute`.

```bash
curl http://localhost:8000/documents/<doc_id>/coordinates
```

### `GET /documents/stats` — статистика хранилища

```bash
curl http://localhost:8000/documents/stats
```

## Управление

```bash
# Запуск
docker-compose up --build -d

# Логи
docker-compose logs -f

# Остановка
docker-compose down

# Или через скрипты
./start.sh --build
./stop.sh
```

## Пайплайн обработки

```
PDF → Split (pdftoppm) → OSD (ориентация) → Deskew (наклон) → OCR (Tesseract) → JSON
         ↓                    ↓                  ↓                  ↓
    PDF → images        определение          коррекция        распознавание
    (параллельно)       поворота 0/90/       угла наклона     текста + координат
                        180/270°             (>0.3°)          (все ядра CPU)
```

Все тяжёлые этапы выполняются параллельно через `ProcessPoolExecutor`.

## Структура проекта

```
├── ocr/
│   ├── main.py              # FastAPI приложение (эндпоинты)
│   ├── config.py             # Настройки из .env
│   ├── schemas.py            # Pydantic-модели + dataclass'ы координат
│   └── services/
│       ├── pdf_processor.py  # PDF → images (pdftoppm)
│       ├── osd_worker.py     # Определение ориентации
│       ├── skew_worker.py    # Коррекция наклона
│       ├── ocr_processor.py  # OCR + координация пайплайна
│       └── coordinates_store.py  # In-memory хранилище координат
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example              # Шаблон конфигурации с документацией
├── start.sh / stop.sh        # Скрипты управления
└── tests/                    # Отладочные тесты пайплайна
```
