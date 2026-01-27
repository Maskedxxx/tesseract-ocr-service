"""
Модуль для A/B сравнения двух подходов к OCR.

Содержит две реализации:
    - ocr_old_way: текущий подход (2 вызова Tesseract)
    - ocr_new_way: оптимизированный подход (1 вызов Tesseract)

Цель: показать, что один вызов image_to_data() достаточен
для получения и текста, и confidence.
"""

import time
from dataclasses import dataclass
from typing import Optional

import pytesseract
from PIL import Image


@dataclass
class OCRTestResult:
    """
    Результат тестового OCR для сравнения методов.

    Attributes:
        text: распознанный текст
        confidence: средняя уверенность (0-100)
        time_ms: время выполнения в миллисекундах
        method: название метода ("old" или "new")
    """
    text: str
    confidence: float
    time_ms: int
    method: str


def ocr_old_way(
    image: Image.Image,
    lang: str = "rus",
    config: str = "--oem 3 --psm 3"
) -> OCRTestResult:
    """
    Текущий подход: ДВА вызова Tesseract.

    1) image_to_string — получаем текст
    2) image_to_data — получаем confidence (Tesseract делает OCR заново!)

    Это неэффективно, т.к. Tesseract выполняет полный OCR дважды.

    Args:
        image: PIL изображение для распознавания
        lang: языки Tesseract (например "rus+eng")
        config: конфиг Tesseract (OEM, PSM)

    Returns:
        OCRTestResult: текст, confidence, время
    """
    start = time.perf_counter()

    # Вызов 1: получаем текст
    text = pytesseract.image_to_string(
        image,
        lang=lang,
        config=config,
    )

    # Вызов 2: получаем данные с confidence
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    # Вычисляем среднюю уверенность (только для реальных слов, conf >= 0)
    confidences = [
        int(c) for c in data["conf"]
        if isinstance(c, (int, float)) and int(c) >= 0
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return OCRTestResult(
        text=text,
        confidence=avg_confidence,
        time_ms=elapsed_ms,
        method="old",
    )


def ocr_new_way(
    image: Image.Image,
    lang: str = "rus",
    config: str = "--oem 3 --psm 3"
) -> OCRTestResult:
    """
    Оптимизированный подход: ОДИН вызов Tesseract.

    image_to_data() возвращает ВСЕ данные:
        - text: слова
        - conf: уверенность для каждого слова
        - block_num, par_num, line_num: структура для сборки текста

    Мы извлекаем текст напрямую из data["text"], собирая его
    с учётом структуры блоков/параграфов/строк.

    Args:
        image: PIL изображение для распознавания
        lang: языки Tesseract (например "rus+eng")
        config: конфиг Tesseract (OEM, PSM)

    Returns:
        OCRTestResult: текст, confidence, время
    """
    start = time.perf_counter()

    # ОДИН вызов — получаем ВСЁ
    data = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    # Собираем текст с учётом структуры
    text = _assemble_text_from_data(data)

    # Вычисляем среднюю уверенность
    confidences = [
        int(c) for c in data["conf"]
        if isinstance(c, (int, float)) and int(c) >= 0
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return OCRTestResult(
        text=text,
        confidence=avg_confidence,
        time_ms=elapsed_ms,
        method="new",
    )


def _assemble_text_from_data(data: dict) -> str:
    """
    Собирает текст из словаря image_to_data с правильной структурой.

    Алгоритм:
        - Слова на одной строке (line_num) соединяются пробелами
        - Разные строки в одном параграфе — новая строка (\n)
        - Разные параграфы в одном блоке — новая строка (\n)
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

    # Собираем текст
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


def compare_texts(text1: str, text2: str) -> dict:
    """
    Сравнивает два текста и возвращает метрики схожести.

    Args:
        text1: первый текст
        text2: второй текст

    Returns:
        dict: метрики сравнения
    """
    # Нормализуем для сравнения (убираем лишние пробелы/переносы)
    norm1 = " ".join(text1.split())
    norm2 = " ".join(text2.split())

    # Точное совпадение после нормализации
    exact_match = norm1 == norm2

    # Длины
    len1 = len(norm1)
    len2 = len(norm2)

    # Простая метрика: отношение длин
    if max(len1, len2) > 0:
        length_ratio = min(len1, len2) / max(len1, len2)
    else:
        length_ratio = 1.0

    return {
        "exact_match_normalized": exact_match,
        "len_old": len1,
        "len_new": len2,
        "length_ratio": round(length_ratio, 4),
    }
