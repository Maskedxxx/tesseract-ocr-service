"""
Процессор разбиения PDF на изображения.

Использует pdf2image (pdftoppm) для быстрого рендеринга PDF страниц в JPEG.
Оптимизирован для параллельной обработки.
"""

import io
import logging
from typing import Optional

from pdf2image import convert_from_bytes
from PIL import Image

from ocr_worker.config import settings

logger = logging.getLogger(__name__)


def split_pdf_to_images(
    pdf_bytes: bytes,
    pages: Optional[list[int]] = None,
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
) -> list[tuple[int, Image.Image]]:
    """
    Разбивает PDF на отдельные изображения страниц.

    Использует pdftoppm через pdf2image — быстрый C++ рендеринг
    с многопоточностью.

    Приоритет выбора страниц:
        1. pages — конкретные номера [1, 3, 5]
        2. page_start/page_end — диапазон
        3. Все страницы если ничего не указано

    Args:
        pdf_bytes: содержимое PDF файла в байтах
        pages: список конкретных страниц для обработки
        page_start: начальная страница диапазона
        page_end: конечная страница диапазона

    Returns:
        list[tuple[int, Image.Image]]: список кортежей (номер_страницы, изображение)
            Нумерация страниц начинается с 1.

    Raises:
        ValueError: если PDF не содержит страниц
        Exception: при ошибках рендеринга
    """
    logger.info(
        f"Разбиение PDF: dpi={settings.render_dpi}, "
        f"threads={settings.render_thread_count}"
    )

    # Определяем какие страницы рендерить
    first_page = None
    last_page = None

    if pages:
        # Конкретные страницы — рендерим все, потом отфильтруем
        # (pdf2image не поддерживает произвольный список страниц)
        logger.info(f"Запрошены конкретные страницы: {pages}")
    elif page_start or page_end:
        # Диапазон страниц
        first_page = page_start
        last_page = page_end
        logger.info(f"Запрошен диапазон: {first_page or 1}-{last_page or 'конец'}")

    # Рендерим PDF через pdftoppm
    images = convert_from_bytes(
        pdf_bytes,
        dpi=settings.render_dpi,
        fmt=settings.render_format,
        thread_count=settings.render_thread_count,
        first_page=first_page,
        last_page=last_page,
    )

    if not images:
        raise ValueError("PDF не содержит страниц")

    # Формируем список с номерами страниц
    # convert_from_bytes возвращает страницы в порядке first_page..last_page
    # Нумерация с 1
    start_num = first_page or 1
    result = [
        (start_num + idx, img)
        for idx, img in enumerate(images)
    ]

    # Если запрошены конкретные страницы — фильтруем
    if pages:
        pages_set = set(pages)
        result = [
            (page_num, img)
            for page_num, img in result
            if page_num in pages_set
        ]
        logger.info(f"Отфильтровано {len(result)} страниц из {len(images)}")

    logger.info(f"Разбиение завершено: {len(result)} страниц")
    return result


def get_pdf_page_count(pdf_bytes: bytes) -> int:
    """
    Получает количество страниц в PDF без рендеринга.

    Args:
        pdf_bytes: содержимое PDF файла

    Returns:
        int: количество страниц
    """
    # Быстрый способ — рендерим первую страницу с низким dpi
    # и получаем info о количестве страниц
    from pdf2image.pdf2image import pdfinfo_from_bytes

    info = pdfinfo_from_bytes(pdf_bytes)
    return info.get("Pages", 0)
