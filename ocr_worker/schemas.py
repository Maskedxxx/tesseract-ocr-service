"""
Схемы данных для OCR Worker.

Внутренние структуры данных для обмена между компонентами Worker.
"""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel


@dataclass
class PageOrientation:
    """
    Результат определения ориентации страницы (OSD).

    Attributes:
        page_num: номер страницы (начинается с 1)
        rotate: угол поворота в градусах (0, 90, 180, 270)
        confidence: уверенность Tesseract (0-100)
        needs_rotation: флаг необходимости поворота (rotate != 0)
    """

    page_num: int
    rotate: int
    confidence: float
    needs_rotation: bool


@dataclass
class PageSkew:
    """
    Результат определения наклона страницы (deskew).

    Attributes:
        page_num: номер страницы
        angle: угол наклона в градусах (отрицательный = наклон влево)
        needs_deskew: флаг необходимости коррекции
    """

    page_num: int
    angle: float
    needs_deskew: bool


@dataclass
class PageOCRResult:
    """
    Результат OCR для одной страницы.

    Attributes:
        page_num: номер страницы
        text: распознанный текст
        confidence: средняя уверенность (если доступна)
    """

    page_num: int
    text: str
    confidence: float = 0.0


class PageResult(BaseModel):
    """
    Полный результат обработки одной страницы.

    Включает все метаданные обработки для возврата через API.

    Attributes:
        page_number: номер страницы (начинается с 1)
        text: распознанный текст
        confidence: средняя уверенность распознавания (0-100)
        rotation_applied: угол поворота, который был применён
        deskew_angle: угол коррекции наклона
        width: ширина изображения в пикселях
        height: высота изображения в пикселях
        processing_time_ms: время обработки страницы
    """

    page_number: int
    text: str
    confidence: float = 0.0
    rotation_applied: int = 0
    deskew_angle: float = 0.0
    width: int = 0
    height: int = 0
    processing_time_ms: int = 0


class OCRConfigInput(BaseModel):
    """
    Входная конфигурация OCR от Docker API.

    Attributes:
        languages: языки для распознавания
        pages: конкретные страницы для обработки
        page_start: начало диапазона страниц
        page_end: конец диапазона страниц
    """

    languages: list[str] = ["rus"]
    pages: Optional[list[int]] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None


class OCRResult(BaseModel):
    """
    Результат обработки документа для возврата в Docker API.

    Attributes:
        success: успешность операции
        pages: список результатов по страницам
        error: сообщение об ошибке (если success=False)
    """

    success: bool
    pages: list[PageResult] = []
    error: Optional[str] = None
