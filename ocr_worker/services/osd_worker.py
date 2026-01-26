"""
Воркер для определения ориентации текста (OSD — Orientation and Script Detection).

Использует Tesseract OCR для определения угла поворота текста (0, 90, 180, 270°).
Предназначен для использования в ProcessPoolExecutor.

Оптимизации:
    - Crop центральных 70% (убирает шум по краям скана)
    - Resize до 2048px (баланс скорость/точность)
    - Autocontrast (улучшает распознавание)
"""

import logging

import pytesseract
from PIL import Image, ImageOps

from ocr_worker.config import settings
from ocr_worker.schemas import PageOrientation

logger = logging.getLogger(__name__)


def process_osd(args: tuple[int, Image.Image]) -> PageOrientation:
    """
    Определяет ориентацию текста на изображении через Tesseract OSD.

    Выполняет:
        1. Crop центральных 70% (убирает шум по краям сканера)
        2. Resize до 2048px (баланс скорость/точность)
        3. Конвертация в grayscale + autocontrast
        4. Tesseract OSD (--psm 0)

    Args:
        args: кортеж (номер_страницы, PIL.Image)

    Returns:
        PageOrientation: результат с углом поворота и уверенностью
    """
    page_num, img = args

    # 1. Crop: убираем мусор по краям (черные полосы от сканера)
    # Оставляем центральные 70% изображения
    w, h = img.size
    crop_percent = settings.osd_crop_percent
    crop_box = (
        int(w * crop_percent),
        int(h * crop_percent),
        int(w * (1 - crop_percent)),
        int(h * (1 - crop_percent)),
    )

    # Работаем с копией, чтобы не изменить оригинал
    work_img = img.crop(crop_box)

    # 2. Resize: 2048px — баланс скорости и точности
    resize_px = settings.osd_resize_px
    work_img.thumbnail((resize_px, resize_px))

    # 3. Контраст: grayscale + autocontrast для улучшения распознавания
    work_img = work_img.convert("L")
    work_img = ImageOps.autocontrast(work_img)

    # 4. Tesseract OSD
    try:
        osd = pytesseract.image_to_osd(
            work_img,
            config="--psm 0",
            output_type=pytesseract.Output.DICT,
        )
        rotate = osd["rotate"]
        conf = osd["orientation_conf"]
    except Exception:
        # Если OSD не смог определить (мало текста, только картинки)
        rotate = 0
        conf = 0.0

    return PageOrientation(
        page_num=page_num,
        rotate=rotate,
        confidence=conf,
        needs_rotation=rotate != 0,
    )


def apply_rotation(img: Image.Image, rotation: int) -> Image.Image:
    """
    Применяет ОБРАТНЫЙ поворот к изображению для коррекции ориентации.

    Tesseract OSD возвращает угол, на который текст ПОВЁРНУТ относительно нормального.
    Чтобы исправить, нужно повернуть в ОБРАТНУЮ сторону (на -rotation).

    Пример:
        - OSD говорит rotate=90 → текст повёрнут на 90° по часовой
        - Чтобы исправить → поворачиваем на 90° ПРОТИВ часовой (ROTATE_270 в PIL)

    Args:
        img: исходное изображение
        rotation: угол поворота от OSD (0, 90, 180, 270)

    Returns:
        Image.Image: повёрнутое изображение с исправленной ориентацией
    """
    if rotation == 0:
        return img

    # PIL transpose: ROTATE_90 = против часовой, ROTATE_270 = по часовой
    # OSD rotation: угол на который ПОВЁРНУТ текст
    # Коррекция: применяем ОБРАТНЫЙ поворот (360 - rotation)

    if rotation == 90:
        # Текст повёрнут на 90° → исправляем поворотом на -90° (= 270° = по часовой)
        return img.transpose(Image.Transpose.ROTATE_270)
    elif rotation == 180:
        # 180° одинаково в обе стороны
        return img.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        # Текст повёрнут на 270° → исправляем поворотом на -270° (= 90° = против часовой)
        return img.transpose(Image.Transpose.ROTATE_90)
    else:
        # Для произвольных углов: поворачиваем в обратную сторону
        return img.rotate(-rotation, expand=True, fillcolor="white")
