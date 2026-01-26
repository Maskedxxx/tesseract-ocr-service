"""
Docker API для OCR сервиса.

Принимает PDF файл и проксирует запрос к OCR Worker.
Предназначен для запуска в Docker контейнере.
"""

from app.config import settings
from app.schemas import FileInfo, OCRConfig, OCRResponse, PageResult

__all__ = [
    "settings",
    "OCRConfig",
    "OCRResponse",
    "PageResult",
    "FileInfo",
]
