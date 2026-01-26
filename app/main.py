"""
Docker API для OCR сервиса.

Принимает PDF файл + конфигурацию, проксирует запрос к OCR Worker,
возвращает результаты распознавания.

Запуск:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

import json
import logging
import time
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.schemas import FileInfo, OCRConfig, OCRResponse, PageResult

# Настройка логгера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [OCR-API] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# FastAPI приложение
app = FastAPI(
    title="OCR Service API",
    description="API для распознавания текста из PDF документов",
    version="1.0.0",
)


@app.get("/health")
async def health_check() -> dict:
    """
    Проверка работоспособности API и OCR Worker.

    Returns:
        dict: статус API и доступность Worker
    """
    worker_status = "unknown"
    worker_info = {}

    # Проверяем доступность OCR Worker
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{settings.worker_url}/health")
            if response.status_code == 200:
                worker_status = "ok"
                worker_info = response.json()
            else:
                worker_status = f"error: {response.status_code}"
    except httpx.ConnectError:
        worker_status = "unavailable"
    except Exception as e:
        worker_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "service": "ocr-api",
        "worker": {
            "url": settings.worker_url,
            "status": worker_status,
            "info": worker_info,
        },
        "config": {
            "max_file_size_mb": settings.max_file_size_mb,
            "ocr_timeout_seconds": settings.timeout_seconds,
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

    Принимает PDF и опциональную конфигурацию, проксирует к OCR Worker,
    возвращает распознанный текст со всех страниц.

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

    # 3. Отправляем запрос к OCR Worker
    try:
        worker_response = await _call_ocr_worker(file_bytes, ocr_config)
    except httpx.ConnectError:
        logger.error("OCR Worker недоступен")
        raise HTTPException(
            status_code=503,
            detail={
                "error": "worker_unavailable",
                "message": f"OCR Worker недоступен по адресу {settings.worker_url}",
            },
        )
    except httpx.TimeoutException:
        logger.error("Таймаут ожидания OCR Worker")
        raise HTTPException(
            status_code=504,
            detail={
                "error": "worker_timeout",
                "message": f"OCR Worker не ответил за {settings.timeout_seconds} секунд",
            },
        )
    except Exception as e:
        logger.exception(f"Ошибка вызова OCR Worker: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "worker_error",
                "message": str(e),
            },
        )

    # 4. Формируем ответ
    processing_time_ms = int((time.time() - start_time) * 1000)

    # Если Worker вернул ошибку
    if not worker_response.get("success", False):
        return OCRResponse(
            success=False,
            total_pages=0,
            processing_time_ms=processing_time_ms,
            pages=[],
            config_used=ocr_config,
            file_info=file_info,
            error=worker_response.get("error", "Unknown error"),
        )

    # Преобразуем ответ Worker в наш формат
    pages = [
        PageResult(**page_data)
        for page_data in worker_response.get("pages", [])
    ]

    logger.info(
        f"OCR завершён: {len(pages)} страниц за {processing_time_ms}ms"
    )

    return OCRResponse(
        success=True,
        total_pages=len(pages),
        processing_time_ms=processing_time_ms,
        pages=pages,
        config_used=ocr_config,
        file_info=file_info,
    )


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
        - Тип файла (application/pdf)
        - Размер файла (не больше max_file_size_mb)

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


async def _call_ocr_worker(
    file_bytes: bytes,
    config: OCRConfig,
) -> dict:
    """
    Отправляет запрос к OCR Worker.

    Args:
        file_bytes: содержимое PDF файла
        config: конфигурация OCR

    Returns:
        dict: ответ от Worker
    """
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.timeout_seconds)
    ) as client:
        # Формируем multipart запрос
        files = {"file": ("document.pdf", file_bytes, "application/pdf")}
        data = {"config": config.model_dump_json()}

        response = await client.post(
            f"{settings.worker_url}/process",
            files=files,
            data=data,
        )

        if response.status_code != 200:
            raise Exception(
                f"Worker вернул ошибку: {response.status_code} - {response.text}"
            )

        return response.json()


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Запуск OCR API на {settings.host}:{settings.port}")
    logger.info(f"OCR Worker URL: {settings.worker_url}")

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
