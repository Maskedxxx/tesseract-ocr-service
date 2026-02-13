"""
OCR Service v2 — единое приложение для распознавания текста из PDF.

Объединяет API и обработку в одном Docker-контейнере:
    - FastAPI эндпоинты (приём PDF, выдача результатов, координаты)
    - Полный пайплайн: split -> OSD -> deskew -> OCR
    - In-memory хранилище координат для подсветки текста

Все этапы обработки выполняются параллельно через ProcessPoolExecutor.
"""

from ocr.config import settings
from ocr.schemas import OCRConfig, OCRResponse, PageResult, FileInfo

__all__ = [
    "settings",
    "OCRConfig",
    "OCRResponse",
    "PageResult",
    "FileInfo",
]
