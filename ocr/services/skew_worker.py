"""
Воркер для определения угла наклона текста (deskew).

Использует библиотеку deskew для определения мелкого наклона текста (1-5).
Предназначен для использования в ProcessPoolExecutor.

Оптимизации:
    - Resize до 1200px (достаточно для определения наклона)
    - num_peaks=20 (стабильный результат)
"""

import logging

import numpy as np
from deskew import determine_skew
from PIL import Image

from ocr.config import settings
from ocr.schemas import PageSkew

logger = logging.getLogger(__name__)


def process_skew(args: tuple[int, Image.Image]) -> PageSkew:
    """
    Определяет угол наклона текста на изображении.

    Выполняет:
        1. Resize до 1200px по длинной стороне
        2. Конвертация в grayscale
        3. Определение угла через deskew (проекционный профиль)

    Args:
        args: кортеж (номер_страницы, PIL.Image)

    Returns:
        PageSkew: результат с углом наклона
    """
    page_num, img = args

    # 1. Resize: 1200px по длинной стороне
    # На 2500px алгоритм захлебывается, на 600px теряет точность
    w, h = img.size
    resize_px = settings.deskew_resize_px
    ratio = resize_px / max(w, h)
    new_size = (int(w * ratio), int(h * ratio))

    small_img = img.resize(new_size, Image.Resampling.BILINEAR)

    # 2. Grayscale: deskew работает с чб массивами
    grayscale = small_img.convert("L")
    img_array = np.array(grayscale)

    # 3. Deskew: определение угла
    # num_peaks=20 даёт более стабильный результат
    try:
        angle = determine_skew(img_array, num_peaks=settings.deskew_num_peaks)
    except Exception:
        angle = 0.0

    # None -> 0.0
    angle = angle if angle is not None else 0.0

    # Определяем, нужна ли коррекция
    needs_deskew = abs(angle) > settings.skew_threshold

    return PageSkew(
        page_num=page_num,
        angle=angle,
        needs_deskew=needs_deskew,
    )


def apply_deskew(img: Image.Image, angle: float) -> Image.Image:
    """
    Применяет коррекцию наклона к изображению.

    Args:
        img: исходное изображение
        angle: угол коррекции в градусах

    Returns:
        Image.Image: скорректированное изображение
    """
    if abs(angle) < settings.skew_threshold:
        return img

    # Поворачиваем на -angle чтобы скомпенсировать наклон
    # expand=True увеличивает холст чтобы не обрезать углы
    # fillcolor="white" заполняет новые области белым
    return img.rotate(
        -angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor="white",
    )
