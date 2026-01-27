"""
OCR Worker — FastAPI микросервис для распознавания текста.

Принимает PDF файл + конфигурацию, выполняет полный пайплайн:
    split → OSD → deskew → OCR

Запускается локально вне Docker для использования всех ядер CPU хоста
и установленного Tesseract OCR.

Запуск:
    python -m ocr_worker.main

Или:
    uvicorn ocr_worker.main:app --port 8001 --reload
"""

import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from ocr_worker.config import settings
from ocr_worker.schemas import OCRConfigInput, OCRResult
from ocr_worker.services.coordinates_store import get_coordinates, get_store_stats
from ocr_worker.services.ocr_processor import process_document

# Настройка логгера с временем
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OCR-Worker] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# FastAPI приложение
app = FastAPI(
    title="OCR Worker",
    description="Микросервис распознавания текста из PDF (Tesseract OCR)",
    version="1.0.0",
)


@app.get("/health")
async def health_check() -> dict:
    """
    Проверка работоспособности сервиса.

    Returns:
        dict: статус и информация о системе
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
        "service": "ocr-worker",
        "cpu_count": os.cpu_count(),
        "tesseract": {
            "available": tesseract_ok,
            "version": tesseract_version,
        },
        "config": {
            "render_dpi": settings.render_dpi,
            "render_threads": settings.render_thread_count,
            "ocr_oem": settings.ocr_oem,
            "ocr_psm": settings.ocr_psm,
            "skew_threshold": settings.skew_threshold,
        },
    }


@app.post("/process", response_model=OCRResult)
async def process_pdf(
    file: UploadFile = File(..., description="PDF файл для распознавания"),
    config: Optional[str] = Form(
        default=None,
        description='JSON конфигурация: {"languages": ["rus"], "pages": [1, 2, 3]}',
    ),
) -> OCRResult:
    """
    Выполняет распознавание текста из PDF файла.

    Полный пайплайн обработки:
        1. Split: PDF → images (pdftoppm, параллельно)
        2. OSD: определение ориентации (Tesseract, ProcessPoolExecutor)
        3. Deskew: коррекция наклона (deskew, ProcessPoolExecutor)
        4. OCR: распознавание текста (Tesseract, ProcessPoolExecutor)

    Args:
        file: PDF файл (multipart/form-data)
        config: JSON строка с конфигурацией

    Returns:
        OCRResult: результаты распознавания

    Raises:
        HTTPException: при ошибках обработки
    """
    # Парсим конфигурацию
    ocr_config = _parse_config(config)
    logger.info(
        f"Получен файл: {file.filename}, "
        f"языки: {ocr_config.languages}, "
        f"страницы: {ocr_config.pages or 'все'}"
    )

    # Читаем файл
    try:
        pdf_bytes = await file.read()
    except Exception as e:
        logger.error(f"Ошибка чтения файла: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка чтения файла: {e}",
        )

    # Валидация PDF
    if not pdf_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=400,
            detail="Файл не является валидным PDF",
        )

    logger.info(f"Файл прочитан: {len(pdf_bytes)} байт")

    # Выполняем обработку в threadpool чтобы не блокировать event loop
    # (process_document использует ProcessPoolExecutor внутри)
    result = await run_in_threadpool(
        process_document,
        pdf_bytes,
        ocr_config,
    )

    if result.success:
        total_chars = sum(len(p.text) for p in result.pages)
        logger.info(
            f"Успех: {len(result.pages)} страниц, {total_chars} символов, "
            f"doc_id={result.doc_id}"
        )
    else:
        logger.error(f"Ошибка: {result.error}")

    return result


@app.get("/documents/{doc_id}/coordinates")
async def get_document_coordinates(doc_id: str) -> dict:
    """
    Получает координаты всех элементов документа.

    Координаты используются фронтендом для подсветки текста
    при поиске или навигации по документу.

    Args:
        doc_id: UUID документа (из ответа /process)

    Returns:
        dict: иерархия координат (страницы → блоки → параграфы → строки → слова)

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


def _parse_config(config_json: Optional[str]) -> OCRConfigInput:
    """
    Парсит JSON конфигурацию из строки.

    Args:
        config_json: JSON строка или None

    Returns:
        OCRConfigInput: конфигурация с дефолтными значениями если не указано
    """
    if not config_json:
        return OCRConfigInput()

    try:
        config_dict = json.loads(config_json)
        return OCRConfigInput(**config_dict)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Некорректный JSON в config: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка парсинга config: {e}",
        )


if __name__ == "__main__":
    import uvicorn

    port = settings.port
    logger.info(f"Запуск OCR Worker на порту {port}")
    logger.info(f"CPU ядер: {os.cpu_count()}")
    logger.info(
        f"Конфиг: DPI={settings.render_dpi}, "
        f"OEM={settings.ocr_oem}, PSM={settings.ocr_psm}"
    )

    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        log_level="info",
    )
