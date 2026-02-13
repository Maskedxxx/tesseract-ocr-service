"""
Единые схемы данных OCR Service v2.

Включает:
    - Pydantic модели для API (конфигурация, ответ, результат страницы)
    - Внутренние dataclass'ы для пайплайна обработки
    - Структуры координат для подсветки текста на фронтенде
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


# =============================================================================
# Pydantic модели для API
# =============================================================================


class OCRConfig(BaseModel):
    """
    Конфигурация OCR от пользователя.

    Приоритет выбора страниц:
        1. pages — конкретные страницы [1, 3, 5]
        2. page_start/page_end — диапазон
        3. Если ничего не указано — все страницы

    Attributes:
        languages: список языков для OCR (по умолчанию ["rus"])
        pages: конкретные номера страниц для обработки
        page_start: начало диапазона страниц
        page_end: конец диапазона страниц
    """

    languages: list[str] = Field(
        default=["rus"],
        description="Языки для OCR: ['rus'], ['eng'], ['rus', 'eng']",
    )
    pages: Optional[list[int]] = Field(
        default=None,
        description="Конкретные страницы: [1, 3, 5]",
    )
    page_start: Optional[int] = Field(
        default=None,
        description="Начало диапазона страниц",
        ge=1,
    )
    page_end: Optional[int] = Field(
        default=None,
        description="Конец диапазона страниц",
        ge=1,
    )


class PageResult(BaseModel):
    """
    Результат OCR для одной страницы.

    Attributes:
        page_number: номер страницы (начинается с 1)
        text: распознанный текст
        confidence: средняя уверенность распознавания (0-100)
        rotation_applied: угол поворота, который был применён (0, 90, 180, 270)
        deskew_angle: угол коррекции наклона в градусах
        width: ширина изображения в пикселях
        height: высота изображения в пикселях
        processing_time_ms: время обработки страницы в мс
    """

    page_number: int
    text: str
    confidence: float = 0.0
    rotation_applied: int = 0
    deskew_angle: float = 0.0
    width: int = 0
    height: int = 0
    processing_time_ms: int = 0


class FileInfo(BaseModel):
    """
    Информация о загруженном файле.

    Attributes:
        filename: имя файла
        size_bytes: размер файла в байтах
    """

    filename: str
    size_bytes: int


class OCRResponse(BaseModel):
    """
    Ответ API с результатами OCR.

    Attributes:
        success: успешность операции
        doc_id: UUID документа для запроса координат
        total_pages: общее количество обработанных страниц
        processing_time_ms: общее время обработки в мс
        pages: список результатов по страницам
        config_used: конфигурация, которая была использована
        file_info: информация о файле
        error: сообщение об ошибке (если success=False)
    """

    success: bool
    doc_id: Optional[str] = None
    total_pages: int
    processing_time_ms: int
    pages: list[PageResult] = []
    config_used: OCRConfig
    file_info: FileInfo
    error: Optional[str] = None


# =============================================================================
# Внутренние dataclass'ы для пайплайна
# =============================================================================


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
