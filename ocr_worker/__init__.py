"""
OCR Worker — микросервис распознавания текста из PDF.

Выполняет полный пайплайн:
    - Split: PDF → images (pdf2image/pdftoppm)
    - OSD: определение ориентации (Tesseract)
    - Deskew: коррекция наклона (deskew)
    - OCR: распознавание текста (Tesseract)

Все этапы выполняются параллельно через ProcessPoolExecutor.
"""

from ocr_worker.config import settings
from ocr_worker.schemas import OCRConfigInput, OCRResult, PageResult

__all__ = [
    "settings",
    "OCRConfigInput",
    "OCRResult",
    "PageResult",
]
