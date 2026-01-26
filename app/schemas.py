"""
Схемы данных для Docker API.

Определяет формат конфигурации от пользователя и ответа с результатами OCR.
"""

from typing import Optional

from pydantic import BaseModel, Field


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
        total_pages: общее количество обработанных страниц
        processing_time_ms: общее время обработки в мс
        pages: список результатов по страницам
        config_used: конфигурация, которая была использована
        file_info: информация о файле
        error: сообщение об ошибке (если success=False)
    """

    success: bool
    total_pages: int
    processing_time_ms: int
    pages: list[PageResult] = []
    config_used: OCRConfig
    file_info: FileInfo
    error: Optional[str] = None
