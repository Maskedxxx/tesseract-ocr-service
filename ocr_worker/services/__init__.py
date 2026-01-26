"""
Сервисы OCR Worker.

Модули:
    - pdf_processor: разбиение PDF на изображения
    - osd_worker: определение ориентации текста
    - skew_worker: определение и коррекция наклона
    - ocr_processor: распознавание текста + координация пайплайна
"""

from ocr_worker.services.ocr_processor import process_document
from ocr_worker.services.osd_worker import apply_rotation, process_osd
from ocr_worker.services.pdf_processor import split_pdf_to_images
from ocr_worker.services.skew_worker import apply_deskew, process_skew

__all__ = [
    "process_document",
    "split_pdf_to_images",
    "process_osd",
    "apply_rotation",
    "process_skew",
    "apply_deskew",
]
