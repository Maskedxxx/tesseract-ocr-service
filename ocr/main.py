"""
OCR Service v2 — единое FastAPI приложение.

Объединяет API (приём PDF, валидация) и OCR обработку (пайплайн)
в одном приложении для запуска в Docker-контейнере.

Эндпоинты:
    POST /ocr/execute — загрузка PDF и распознавание текста
    GET  /health — проверка работоспособности (Tesseract + CPU + конфиг)
    GET  /documents/{doc_id}/coordinates — координаты элементов документа
    GET  /documents/stats — статистика хранилища координат

Запуск:
    uvicorn ocr.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ocr.config import settings
from ocr.schemas import FileInfo, OCRConfig, OCRResponse, PageResult
from ocr.services.coordinates_store import get_coordinates, get_store_stats
from ocr.services.ocr_processor import process_document

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OCR-Service] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class UnicodeJSONResponse(JSONResponse):
    """JSON ответ с нормальным отображением кириллицы (без \\uXXXX экранирования)."""

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")


# FastAPI приложение
app = FastAPI(
    title="OCR Service",
    description="Сервис распознавания текста из PDF документов (Tesseract OCR)",
    version="2.0.0",
    default_response_class=UnicodeJSONResponse,
)


@app.get("/health")
async def health_check() -> dict:
    """
    Проверка работоспособности сервиса.

    Проверяет доступность Tesseract, количество CPU,
    и возвращает текущую конфигурацию.

    Returns:
        dict: статус сервиса и информация о системе
    """
    # Проверяем доступность Tesseract
    tesseract_ok = False
    tesseract_version = "unknown"
    try:
        import pytesseract
        tesseract_version = pytesseract.get_tesseract_version().public
        tesseract_ok = True
    except Exception as e:
        tesseract_version = f"error: {e}"

    return {
        "status": "ok" if tesseract_ok else "degraded",
        "service": "ocr-service",
        "version": "2.0.0",
        "cpu_count": os.cpu_count(),
        "tesseract": {
            "available": tesseract_ok,
            "version": tesseract_version,
        },
        "config": {
            "max_file_size_mb": settings.max_file_size_mb,
            "render_dpi": settings.render_dpi,
            "render_threads": settings.render_thread_count,
            "ocr_oem": settings.ocr_oem,
            "ocr_psm": settings.ocr_psm,
            "skew_threshold": settings.skew_threshold,
        },
    }


@app.post("/ocr/execute", response_model=OCRResponse)
async def execute_ocr(
    file: UploadFile = File(..., description="PDF файл для распознавания"),
    config: Optional[str] = Form(
        default=None,
        description='JSON конфигурация: {"languages": ["rus"], "pages": [1, 2, 3]}',
    ),
) -> OCRResponse:
    """
    Выполняет распознавание текста из PDF файла.

    Принимает PDF и опциональную конфигурацию, выполняет полный пайплайн:
        split -> OSD -> deskew -> OCR

    Args:
        file: PDF файл (multipart/form-data)
        config: JSON строка с конфигурацией OCR

    Returns:
        OCRResponse: результаты распознавания

    Raises:
        HTTPException: при ошибках валидации или обработки
    """
    start_time = time.time()

    # 1. Парсим конфигурацию
    ocr_config = _parse_config(config)
    logger.info(f"Получен файл: {file.filename}, конфиг: {ocr_config.model_dump()}")

    # 2. Читаем и валидируем файл
    file_bytes = await _validate_and_read_file(file)
    file_info = FileInfo(
        filename=file.filename or "unknown.pdf",
        size_bytes=len(file_bytes),
    )
    logger.info(f"Файл прочитан: {file_info.size_bytes} байт")

    # 3. Выполняем OCR — прямой вызов process_document через threadpool
    # (process_document использует ProcessPoolExecutor внутри)
    try:
        worker_response = await run_in_threadpool(
            process_document,
            file_bytes,
            ocr_config,
            file.filename or "unknown.pdf",
        )
    except Exception as e:
        logger.exception(f"Ошибка обработки документа: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "processing_error",
                "message": str(e),
            },
        )

    # 4. Формируем ответ
    processing_time_ms = int((time.time() - start_time) * 1000)

    # Если обработка не удалась
    if not worker_response.get("success", False):
        return OCRResponse(
            success=False,
            doc_id=worker_response.get("doc_id"),
            total_pages=0,
            processing_time_ms=processing_time_ms,
            pages=[],
            config_used=ocr_config,
            file_info=file_info,
            error=worker_response.get("error", "Unknown error"),
        )

    # Преобразуем результат в PageResult
    pages = [
        PageResult(**page_data)
        for page_data in worker_response.get("pages", [])
    ]

    logger.info(
        f"OCR завершён: {len(pages)} страниц за {processing_time_ms}ms"
    )

    return OCRResponse(
        success=True,
        doc_id=worker_response.get("doc_id"),
        total_pages=len(pages),
        processing_time_ms=processing_time_ms,
        pages=pages,
        config_used=ocr_config,
        file_info=file_info,
    )


@app.get("/documents/{doc_id}/coordinates")
async def get_document_coordinates(doc_id: str) -> dict:
    """
    Получает координаты всех элементов документа.

    Координаты используются фронтендом для подсветки текста
    при поиске или навигации по документу.

    Args:
        doc_id: UUID документа (из ответа /ocr/execute)

    Returns:
        dict: иерархия координат (страницы -> блоки -> параграфы -> строки -> слова)

    Raises:
        HTTPException: 404 если документ не найден
    """
    logger.info(f"Запрос координат: doc_id={doc_id}")

    document = get_coordinates(doc_id)

    if document is None:
        logger.warning(f"Документ не найден: {doc_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Документ с id={doc_id} не найден. "
            "Возможно, координаты были удалены или сервис был перезапущен.",
        )

    # Преобразуем dataclass в dict для JSON ответа
    return _document_to_dict(document)


@app.get("/documents/stats")
async def get_documents_stats() -> dict:
    """
    Статистика хранилища координат.

    Полезно для мониторинга использования памяти.

    Returns:
        dict: количество документов, самый старый/новый
    """
    return get_store_stats()


def _document_to_dict(document) -> dict:
    """
    Преобразует DocumentCoordinates в словарь для JSON.

    Args:
        document: DocumentCoordinates объект

    Returns:
        dict: сериализуемый словарь
    """
    return {
        "doc_id": document.doc_id,
        "created_at": document.created_at.isoformat(),
        "pages": [
            {
                "page_number": page.page_number,
                "width": page.width,
                "height": page.height,
                "blocks": [
                    {
                        "block_id": block.block_id,
                        "bbox": block.bbox,
                        "paragraphs": [
                            {
                                "par_id": par.par_id,
                                "bbox": par.bbox,
                                "lines": [
                                    {
                                        "line_id": line.line_id,
                                        "text": line.text,
                                        "bbox": line.bbox,
                                        "words": [
                                            {
                                                "text": word.text,
                                                "left": word.left,
                                                "top": word.top,
                                                "width": word.width,
                                                "height": word.height,
                                                "conf": word.conf,
                                            }
                                            for word in line.words
                                        ],
                                    }
                                    for line in par.lines
                                ],
                            }
                            for par in block.paragraphs
                        ],
                    }
                    for block in page.blocks
                ],
            }
            for page in document.pages
        ],
    }


def _parse_config(config_json: Optional[str]) -> OCRConfig:
    """
    Парсит JSON конфигурацию из строки.

    Args:
        config_json: JSON строка или None

    Returns:
        OCRConfig: конфигурация с дефолтными значениями если не указано
    """
    if not config_json:
        return OCRConfig()

    try:
        config_dict = json.loads(config_json)
        return OCRConfig(**config_dict)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_config",
                "message": f"Некорректный JSON в config: {str(e)}",
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_config",
                "message": f"Ошибка парсинга config: {str(e)}",
            },
        )


async def _validate_and_read_file(file: UploadFile) -> bytes:
    """
    Валидирует и читает загруженный файл.

    Проверяет:
        - Тип файла (application/pdf или application/octet-stream)
        - Размер файла (не больше max_file_size_mb)
        - PDF сигнатуру (%PDF)

    Args:
        file: загруженный файл

    Returns:
        bytes: содержимое файла

    Raises:
        HTTPException: при ошибках валидации
    """
    # Проверяем Content-Type
    if file.content_type and file.content_type != "application/pdf":
        # Разрешаем octet-stream, так как многие клиенты не указывают тип
        if file.content_type != "application/octet-stream":
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "invalid_file_type",
                    "message": f"Ожидается PDF файл, получен: {file.content_type}",
                },
            )

    # Читаем файл
    file_bytes = await file.read()

    # Проверяем размер
    max_size = settings.max_file_size_mb * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "file_too_large",
                "message": f"Файл слишком большой: {len(file_bytes)} байт, "
                f"максимум: {settings.max_file_size_mb} МБ",
            },
        )

    # Проверяем PDF сигнатуру (%PDF)
    if not file_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_pdf",
                "message": "Файл не является валидным PDF (отсутствует сигнатура %PDF)",
            },
        )

    return file_bytes


if __name__ == "__main__":
    import uvicorn

    port = settings.port
    logger.info(f"Запуск OCR Service v2 на порту {port}")
    logger.info(f"CPU ядер: {os.cpu_count()}")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
