"""
Схемы данных для OCR Worker.

Внутренние структуры данных для обмена между компонентами Worker.

Включает:
    - Внутренние dataclass'ы для пайплайна обработки
    - Pydantic модели для API ответов
    - Структуры координат для подсветки текста на фронтенде
"""

from dataclasses import dataclass, field
from datetime import datetime
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
        doc_id: уникальный идентификатор документа для получения координат
        pages: список результатов по страницам
        error: сообщение об ошибке (если success=False)
    """

    success: bool
    doc_id: Optional[str] = None  # UUID для запроса координат
    pages: list[PageResult] = []
    error: Optional[str] = None


# =============================================================================
# Схемы координат для подсветки текста
# =============================================================================


@dataclass
class WordCoordinates:
    """
    Координаты одного слова на странице.

    Используется для подсветки найденного текста на фронтенде.

    Attributes:
        text: распознанный текст слова
        left: X координата левого края (пиксели)
        top: Y координата верхнего края (пиксели)
        width: ширина bounding box слова
        height: высота bounding box слова
        conf: уверенность распознавания (0-100)
    """

    text: str
    left: int
    top: int
    width: int
    height: int
    conf: int


@dataclass
class LineCoordinates:
    """
    Координаты строки текста.

    Строка — последовательность слов на одном уровне по вертикали.

    Attributes:
        line_id: номер строки в параграфе
        text: полный текст строки (слова через пробел)
        bbox: bounding box строки {left, top, right, bottom}
        words: список слов с их координатами
    """

    line_id: int
    text: str
    bbox: dict  # {left, top, right, bottom}
    words: list[WordCoordinates] = field(default_factory=list)


@dataclass
class ParagraphCoordinates:
    """
    Координаты параграфа.

    Параграф — группа строк, объединённых логически (по Tesseract).

    Attributes:
        par_id: номер параграфа в блоке
        bbox: bounding box параграфа
        lines: список строк с координатами
    """

    par_id: int
    bbox: dict  # {left, top, right, bottom}
    lines: list[LineCoordinates] = field(default_factory=list)


@dataclass
class BlockCoordinates:
    """
    Координаты текстового блока.

    Блок — область страницы с текстом (колонка, абзац и т.д.).

    Attributes:
        block_id: номер блока на странице
        bbox: bounding box блока
        paragraphs: список параграфов с координатами
    """

    block_id: int
    bbox: dict  # {left, top, right, bottom}
    paragraphs: list[ParagraphCoordinates] = field(default_factory=list)


@dataclass
class PageCoordinates:
    """
    Координаты всех элементов на одной странице.

    Attributes:
        page_number: номер страницы (начинается с 1)
        width: ширина страницы в пикселях
        height: высота страницы в пикселях
        blocks: список блоков с координатами
    """

    page_number: int
    width: int
    height: int
    blocks: list[BlockCoordinates] = field(default_factory=list)


@dataclass
class DocumentCoordinates:
    """
    Координаты всех элементов документа.

    Корневая структура для хранения координат всего документа.

    Attributes:
        doc_id: уникальный UUID документа
        created_at: время создания записи
        pages: список страниц с координатами
    """

    doc_id: str
    created_at: datetime
    pages: list[PageCoordinates] = field(default_factory=list)
