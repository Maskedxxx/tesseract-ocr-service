"""
Процессор OCR — ядро распознавания текста.

Содержит:
    - Функцию распознавания текста через Tesseract
    - Главную функцию process_document, координирующую весь пайплайн:
      split → OSD → deskew → OCR

Параллелизация:
    - Split: многопоточный pdftoppm
    - OSD, Deskew, OCR: ProcessPoolExecutor на всех ядрах CPU
"""

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from typing import Optional

import pytesseract
from PIL import Image

from ocr_worker.config import settings
from ocr_worker.schemas import (
    OCRConfigInput,
    OCRResult,
    PageOCRResult,
    PageResult,
)
from ocr_worker.services.osd_worker import apply_rotation, process_osd
from ocr_worker.services.pdf_processor import split_pdf_to_images
from ocr_worker.services.skew_worker import apply_deskew, process_skew

logger = logging.getLogger(__name__)


def process_ocr(args: tuple[int, Image.Image, str]) -> PageOCRResult:
    """
    Распознаёт текст на одной странице через Tesseract.

    ОПТИМИЗИРОВАНО: один вызов image_to_data вместо двух вызовов
    (image_to_string + image_to_data). Даёт ускорение ~2x.

    Args:
        args: кортеж (номер_страницы, PIL.Image, lang_string)
            lang_string: языки в формате Tesseract (например "rus+eng")

    Returns:
        PageOCRResult: результат с текстом и уверенностью
    """
    page_num, image, lang = args

    # Формируем конфиг Tesseract
    config = f"--oem {settings.ocr_oem} --psm {settings.ocr_psm}"

    try:
        # ОДИН вызов Tesseract — получаем ВСЕ данные (текст + confidence)
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=pytesseract.Output.DICT,
        )

        # Собираем текст из data с учётом структуры блоков/строк
        text = _assemble_text_from_data(data)

        # Вычисляем среднюю уверенность (только для реальных слов, conf >= 0)
        confidences = [
            int(c)
            for c in data["conf"]
            if isinstance(c, (int, float)) and int(c) >= 0
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    except Exception as e:
        logger.warning(f"Ошибка OCR страницы {page_num}: {e}")
        text = ""
        avg_confidence = 0.0

    return PageOCRResult(
        page_num=page_num,
        text=text,
        confidence=avg_confidence,
    )


def _assemble_text_from_data(data: dict) -> str:
    """
    Собирает текст из словаря image_to_data с правильной структурой.

    Алгоритм:
        - Слова на одной строке (line_num) соединяются пробелами
        - Разные строки в одном блоке — новая строка (\n)
        - Разные блоки — пустая строка между ними (\n\n)

    Args:
        data: словарь от pytesseract.image_to_data()

    Returns:
        str: собранный текст с правильной структурой
    """
    n = len(data["text"])

    # Структура: {block_num: {par_num: {line_num: [words]}}}
    blocks = {}

    for i in range(n):
        word = data["text"][i].strip()
        if not word:  # Пропускаем пустые записи
            continue

        block = data["block_num"][i]
        par = data["par_num"][i]
        line = data["line_num"][i]

        if block not in blocks:
            blocks[block] = {}
        if par not in blocks[block]:
            blocks[block][par] = {}
        if line not in blocks[block][par]:
            blocks[block][par][line] = []

        blocks[block][par][line].append(word)

    # Собираем текст: блоки → параграфы → строки → слова
    result_blocks = []

    for block_num in sorted(blocks.keys()):
        block_lines = []
        for par_num in sorted(blocks[block_num].keys()):
            for line_num in sorted(blocks[block_num][par_num].keys()):
                words = blocks[block_num][par_num][line_num]
                line_text = " ".join(words)
                block_lines.append(line_text)

        result_blocks.append("\n".join(block_lines))

    # Блоки разделяем двойным переносом строки
    return "\n\n".join(result_blocks)


def process_document(
    pdf_bytes: bytes,
    config: OCRConfigInput,
) -> OCRResult:
    """
    Основная функция обработки документа.

    Координирует весь пайплайн:
        1. Split: PDF → images (параллельно через pdftoppm)
        2. OSD: определение ориентации (ProcessPoolExecutor)
        3. Применение поворотов
        4. Deskew: определение наклона (ProcessPoolExecutor)
        5. Применение коррекции наклона
        6. OCR: распознавание текста (ProcessPoolExecutor)
        7. Сборка результата

    Args:
        pdf_bytes: содержимое PDF файла
        config: конфигурация OCR (языки, страницы)

    Returns:
        OCRResult: результат обработки со всеми страницами
    """
    total_start = time.perf_counter()

    # Формируем строку языков для Tesseract
    lang_string = "+".join(config.languages)
    logger.info(f"Начало обработки документа, языки: {lang_string}")

    try:
        # 1. Split: PDF → images
        logger.info("Этап 1: Разбиение PDF на изображения...")
        split_start = time.perf_counter()

        images = split_pdf_to_images(
            pdf_bytes,
            pages=config.pages,
            page_start=config.page_start,
            page_end=config.page_end,
        )

        split_duration = int((time.perf_counter() - split_start) * 1000)
        logger.info(f"Split завершён: {len(images)} страниц за {split_duration}ms")

        if not images:
            return OCRResult(
                success=False,
                error="PDF не содержит страниц для обработки",
            )

        # Количество CPU для параллелизации
        cpu_count = os.cpu_count() or 4
        logger.info(f"Параллельная обработка на {cpu_count} ядрах CPU")

        # 2. OSD: определение ориентации
        logger.info("Этап 2: Определение ориентации страниц (OSD)...")
        osd_start = time.perf_counter()

        with ProcessPoolExecutor() as executor:
            osd_results = list(executor.map(process_osd, images))

        osd_duration = int((time.perf_counter() - osd_start) * 1000)
        rotated_count = sum(1 for r in osd_results if r.needs_rotation)
        logger.info(
            f"OSD завершён: {rotated_count} страниц требуют поворота, "
            f"{osd_duration}ms"
        )

        # 3. Применяем повороты
        rotations = {r.page_num: r.rotate for r in osd_results}
        images_rotated = []
        for page_num, img in images:
            rotation = rotations.get(page_num, 0)
            if rotation != 0:
                img = apply_rotation(img, rotation)
            images_rotated.append((page_num, img))

        # 4. Deskew: определение наклона
        logger.info("Этап 3: Определение наклона страниц (Deskew)...")
        deskew_start = time.perf_counter()

        with ProcessPoolExecutor() as executor:
            skew_results = list(executor.map(process_skew, images_rotated))

        deskew_duration = int((time.perf_counter() - deskew_start) * 1000)
        deskewed_count = sum(1 for r in skew_results if r.needs_deskew)
        logger.info(
            f"Deskew завершён: {deskewed_count} страниц с наклоном, "
            f"{deskew_duration}ms"
        )

        # 5. Применяем коррекцию наклона
        skew_angles = {r.page_num: r.angle for r in skew_results}
        images_corrected = []
        for page_num, img in images_rotated:
            angle = skew_angles.get(page_num, 0.0)
            if abs(angle) > settings.skew_threshold:
                img = apply_deskew(img, angle)
            images_corrected.append((page_num, img))

        # 6. OCR: распознавание текста
        logger.info("Этап 4: Распознавание текста (OCR)...")
        ocr_start = time.perf_counter()

        # Добавляем lang_string к каждому элементу для передачи в worker
        ocr_args = [
            (page_num, img, lang_string)
            for page_num, img in images_corrected
        ]

        with ProcessPoolExecutor() as executor:
            ocr_results = list(executor.map(process_ocr, ocr_args))

        ocr_duration = int((time.perf_counter() - ocr_start) * 1000)
        total_chars = sum(len(r.text) for r in ocr_results)
        logger.info(
            f"OCR завершён: {total_chars} символов, {ocr_duration}ms"
        )

        # 7. Собираем результат
        total_duration = int((time.perf_counter() - total_start) * 1000)

        # Формируем PageResult для каждой страницы
        page_results = []
        for ocr_result in ocr_results:
            page_num = ocr_result.page_num

            # Находим размеры финального изображения
            img_for_page = next(
                (img for pn, img in images_corrected if pn == page_num),
                None
            )
            width, height = img_for_page.size if img_for_page else (0, 0)

            page_results.append(
                PageResult(
                    page_number=page_num,
                    text=ocr_result.text,
                    confidence=ocr_result.confidence,
                    rotation_applied=rotations.get(page_num, 0),
                    deskew_angle=skew_angles.get(page_num, 0.0),
                    width=width,
                    height=height,
                    processing_time_ms=0,  # Общее время делим позже
                )
            )

        # Сортируем по номеру страницы
        page_results.sort(key=lambda p: p.page_number)

        logger.info(
            f"Обработка завершена: {len(page_results)} страниц, "
            f"{total_chars} символов, {total_duration}ms"
        )

        return OCRResult(
            success=True,
            pages=page_results,
        )

    except Exception as e:
        logger.exception(f"Ошибка обработки документа: {e}")
        return OCRResult(
            success=False,
            error=str(e),
        )
