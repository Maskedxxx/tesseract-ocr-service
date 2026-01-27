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
    BlockCoordinates,
    LineCoordinates,
    OCRConfigInput,
    OCRResult,
    PageCoordinates,
    PageOCRResult,
    PageResult,
    ParagraphCoordinates,
    WordCoordinates,
)
from ocr_worker.services.coordinates_store import save_coordinates
from ocr_worker.services.osd_worker import apply_rotation, process_osd
from ocr_worker.services.pdf_processor import split_pdf_to_images
from ocr_worker.services.skew_worker import apply_deskew, process_skew

logger = logging.getLogger(__name__)


def process_ocr(
    args: tuple[int, Image.Image, str],
) -> tuple[PageOCRResult, PageCoordinates]:
    """
    Распознаёт текст на одной странице через Tesseract.

    ОПТИМИЗИРОВАНО: один вызов image_to_data вместо двух вызовов
    (image_to_string + image_to_data). Даёт ускорение ~2x.

    Также извлекает координаты всех элементов для подсветки текста.

    Args:
        args: кортеж (номер_страницы, PIL.Image, lang_string)
            lang_string: языки в формате Tesseract (например "rus+eng")

    Returns:
        tuple: (PageOCRResult, PageCoordinates)
            - PageOCRResult: результат с текстом и уверенностью
            - PageCoordinates: координаты всех элементов страницы
    """
    page_num, image, lang = args

    # Получаем размеры изображения для координат
    page_width, page_height = image.size

    # Формируем конфиг Tesseract
    config = f"--oem {settings.ocr_oem} --psm {settings.ocr_psm}"

    try:
        # ОДИН вызов Tesseract — получаем ВСЕ данные (текст + confidence + координаты)
        data = pytesseract.image_to_data(
            image,
            lang=lang,
            config=config,
            output_type=pytesseract.Output.DICT,
        )

        # Собираем текст из data с учётом структуры блоков/строк
        text = _assemble_text_from_data(data)

        # Извлекаем координаты из тех же данных
        coordinates = _extract_coordinates_from_data(
            data, page_num, page_width, page_height
        )

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
        # Пустые координаты при ошибке
        coordinates = PageCoordinates(
            page_number=page_num,
            width=page_width,
            height=page_height,
            blocks=[],
        )

    ocr_result = PageOCRResult(
        page_num=page_num,
        text=text,
        confidence=avg_confidence,
    )

    return ocr_result, coordinates


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


def _extract_coordinates_from_data(
    data: dict,
    page_num: int,
    page_width: int,
    page_height: int,
) -> PageCoordinates:
    """
    Извлекает координаты всех элементов из словаря image_to_data.

    Строит иерархию: Block → Paragraph → Line → Word с bounding box
    для каждого уровня.

    Args:
        data: словарь от pytesseract.image_to_data()
        page_num: номер страницы
        page_width: ширина страницы в пикселях
        page_height: высота страницы в пикселях

    Returns:
        PageCoordinates: полная структура координат страницы
    """
    n = len(data["text"])

    # Структура для сбора данных:
    # {block_num: {par_num: {line_num: [word_data]}}}
    blocks_data: dict = {}

    # Проход по всем элементам
    for i in range(n):
        word_text = data["text"][i].strip()
        if not word_text:  # Пропускаем пустые записи
            continue

        block_num = data["block_num"][i]
        par_num = data["par_num"][i]
        line_num = data["line_num"][i]

        # Координаты слова
        word = WordCoordinates(
            text=word_text,
            left=data["left"][i],
            top=data["top"][i],
            width=data["width"][i],
            height=data["height"][i],
            conf=int(data["conf"][i]) if data["conf"][i] >= 0 else 0,
        )

        # Добавляем в иерархию
        if block_num not in blocks_data:
            blocks_data[block_num] = {}
        if par_num not in blocks_data[block_num]:
            blocks_data[block_num][par_num] = {}
        if line_num not in blocks_data[block_num][par_num]:
            blocks_data[block_num][par_num][line_num] = []

        blocks_data[block_num][par_num][line_num].append(word)

    # Собираем структуру координат
    blocks: list[BlockCoordinates] = []

    for block_num in sorted(blocks_data.keys()):
        paragraphs: list[ParagraphCoordinates] = []

        for par_num in sorted(blocks_data[block_num].keys()):
            lines: list[LineCoordinates] = []

            for line_num in sorted(blocks_data[block_num][par_num].keys()):
                words = blocks_data[block_num][par_num][line_num]

                # Вычисляем bbox строки (охватывающий все слова)
                line_bbox = _compute_bbox(words)
                line_text = " ".join(w.text for w in words)

                lines.append(
                    LineCoordinates(
                        line_id=line_num,
                        text=line_text,
                        bbox=line_bbox,
                        words=words,
                    )
                )

            # Вычисляем bbox параграфа
            par_bbox = _compute_bbox_from_bboxes([ln.bbox for ln in lines])

            paragraphs.append(
                ParagraphCoordinates(
                    par_id=par_num,
                    bbox=par_bbox,
                    lines=lines,
                )
            )

        # Вычисляем bbox блока
        block_bbox = _compute_bbox_from_bboxes([p.bbox for p in paragraphs])

        blocks.append(
            BlockCoordinates(
                block_id=block_num,
                bbox=block_bbox,
                paragraphs=paragraphs,
            )
        )

    return PageCoordinates(
        page_number=page_num,
        width=page_width,
        height=page_height,
        blocks=blocks,
    )


def _compute_bbox(words: list[WordCoordinates]) -> dict:
    """
    Вычисляет bounding box, охватывающий все слова.

    Args:
        words: список слов с координатами

    Returns:
        dict: {left, top, right, bottom}
    """
    if not words:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}

    left = min(w.left for w in words)
    top = min(w.top for w in words)
    right = max(w.left + w.width for w in words)
    bottom = max(w.top + w.height for w in words)

    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _compute_bbox_from_bboxes(bboxes: list[dict]) -> dict:
    """
    Вычисляет охватывающий bbox из списка bbox'ов.

    Args:
        bboxes: список bbox словарей

    Returns:
        dict: {left, top, right, bottom}
    """
    if not bboxes:
        return {"left": 0, "top": 0, "right": 0, "bottom": 0}

    left = min(b["left"] for b in bboxes)
    top = min(b["top"] for b in bboxes)
    right = max(b["right"] for b in bboxes)
    bottom = max(b["bottom"] for b in bboxes)

    return {"left": left, "top": top, "right": right, "bottom": bottom}


def process_document(
    pdf_bytes: bytes,
    config: OCRConfigInput,
    filename: str = "unknown.pdf",
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
        filename: имя файла для логирования

    Returns:
        OCRResult: результат обработки со всеми страницами
    """
    total_start = time.perf_counter()

    # Формируем строку языков для Tesseract
    lang_string = "+".join(config.languages)

    # Определяем какие страницы запрошены
    pages_requested = "все"
    if config.pages:
        pages_requested = f"страницы {config.pages}"
    elif config.page_start or config.page_end:
        pages_requested = f"страницы {config.page_start or 1}-{config.page_end or 'конец'}"

    # Размер файла
    file_size_mb = len(pdf_bytes) / (1024 * 1024)

    logger.info("=" * 60)
    logger.info(f"📄 НОВЫЙ ЗАПРОС OCR")
    logger.info(f"   Файл: {filename} ({file_size_mb:.2f} MB)")
    logger.info(f"   Страницы: {pages_requested}")
    logger.info(f"   Языки: {lang_string}")
    logger.info("=" * 60)

    try:
        # 1. Split: PDF → images
        split_start = time.perf_counter()

        images = split_pdf_to_images(
            pdf_bytes,
            pages=config.pages,
            page_start=config.page_start,
            page_end=config.page_end,
        )

        split_duration = int((time.perf_counter() - split_start) * 1000)
        logger.info(f"   ✓ Split: {len(images)} страниц за {split_duration}ms")

        if not images:
            return OCRResult(
                success=False,
                error="PDF не содержит страниц для обработки",
            )

        # Количество CPU для параллелизации
        cpu_count = os.cpu_count() or 4

        # 2. OSD: определение ориентации
        osd_start = time.perf_counter()

        with ProcessPoolExecutor() as executor:
            osd_results = list(executor.map(process_osd, images))

        osd_duration = int((time.perf_counter() - osd_start) * 1000)
        rotated_pages = [r for r in osd_results if r.needs_rotation]

        logger.info(f"   ✓ OSD: {osd_duration}ms")
        if rotated_pages:
            for r in rotated_pages:
                logger.info(f"        Поворот: стр.{r.page_num} → {r.rotate}°")
        else:
            logger.info(f"        Все страницы в правильной ориентации")

        # 3. Применяем повороты
        rotations = {r.page_num: r.rotate for r in osd_results}
        images_rotated = []
        for page_num, img in images:
            rotation = rotations.get(page_num, 0)
            if rotation != 0:
                img = apply_rotation(img, rotation)
            images_rotated.append((page_num, img))

        # 4. Deskew: определение наклона
        deskew_start = time.perf_counter()

        with ProcessPoolExecutor() as executor:
            skew_results = list(executor.map(process_skew, images_rotated))

        deskew_duration = int((time.perf_counter() - deskew_start) * 1000)
        skewed_pages = [r for r in skew_results if r.needs_deskew]

        logger.info(f"   ✓ Deskew: {deskew_duration}ms")
        if skewed_pages:
            for r in skewed_pages:
                logger.info(f"        Наклон: стр.{r.page_num} → {r.angle:.1f}°")
        else:
            logger.info(f"        Наклон не обнаружен")

        # 5. Применяем коррекцию наклона
        skew_angles = {r.page_num: r.angle for r in skew_results}
        images_corrected = []
        for page_num, img in images_rotated:
            angle = skew_angles.get(page_num, 0.0)
            if abs(angle) > settings.skew_threshold:
                img = apply_deskew(img, angle)
            images_corrected.append((page_num, img))

        # 6. OCR: распознавание текста
        ocr_start = time.perf_counter()

        # Добавляем lang_string к каждому элементу для передачи в worker
        ocr_args = [
            (page_num, img, lang_string)
            for page_num, img in images_corrected
        ]

        with ProcessPoolExecutor() as executor:
            ocr_results_with_coords = list(executor.map(process_ocr, ocr_args))

        # Разделяем результаты OCR и координаты
        ocr_results = [result for result, _ in ocr_results_with_coords]
        page_coordinates = [coords for _, coords in ocr_results_with_coords]

        ocr_duration = int((time.perf_counter() - ocr_start) * 1000)
        total_chars = sum(len(r.text) for r in ocr_results)
        total_words = sum(
            sum(len(line.words) for block in page.blocks
                for par in block.paragraphs for line in par.lines)
            for page in page_coordinates
        )

        # Логируем результат OCR
        logger.info(f"   ✓ OCR: {ocr_duration}ms")
        logger.info(f"        Символов: {total_chars}, Слов: {total_words}")
        for r in ocr_results:
            logger.info(f"        стр.{r.page_num}: {len(r.text)} симв., уверенность {r.confidence:.0f}%")

        # Сохраняем координаты в хранилище
        doc_id = save_coordinates(page_coordinates)

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

        # Средняя уверенность по всем страницам
        avg_confidence = sum(r.confidence for r in ocr_results) / len(ocr_results) if ocr_results else 0

        logger.info("=" * 60)
        logger.info(f"✅ ОБРАБОТКА ЗАВЕРШЕНА")
        logger.info(f"   Файл: {filename}")
        logger.info(f"   Страниц: {len(page_results)}")
        logger.info(f"   Символов: {total_chars}")
        logger.info(f"   Слов: {total_words}")
        logger.info(f"   Средняя уверенность: {avg_confidence:.1f}%")
        logger.info(f"   doc_id: {doc_id}")
        logger.info("-" * 60)
        logger.info(f"   ⏱ Время по этапам:")
        logger.info(f"      Split:  {split_duration}ms")
        logger.info(f"      OSD:    {osd_duration}ms")
        logger.info(f"      Deskew: {deskew_duration}ms")
        logger.info(f"      OCR:    {ocr_duration}ms")
        logger.info(f"      ИТОГО:  {total_duration}ms")
        logger.info("=" * 60)

        return OCRResult(
            success=True,
            doc_id=doc_id,
            pages=page_results,
        )

    except Exception as e:
        logger.exception(f"Ошибка обработки документа: {e}")
        return OCRResult(
            success=False,
            error=str(e),
        )
