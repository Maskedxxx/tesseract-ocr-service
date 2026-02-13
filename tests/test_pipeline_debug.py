"""
Отладочный тест пайплайна OCR с сохранением всех промежуточных этапов.

Сохраняет изображения на каждом шаге для визуальной проверки:
    - 01_original/   — исходные изображения после split
    - 02_rotated/    — после применения поворота (OSD)
    - 03_deskewed/   — после коррекции наклона
    - 04_final/      — финальные изображения перед OCR
    - results.json   — сводка по всем страницам
"""

import io
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Добавляем корневую папку проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytesseract
from PIL import Image, ImageOps

from ocr.config import settings


# ============================================================================
# Функции обработки (копии из ocr_worker, чтобы тест был автономным)
# ============================================================================

def process_osd_with_debug(args: tuple) -> dict:
    """
    OSD с сохранением промежуточных данных для отладки.

    Возвращает словарь со всеми данными для анализа.
    """
    page_num, img_bytes = args

    # Восстанавливаем изображение из bytes
    img = Image.open(io.BytesIO(img_bytes))

    # 1. Crop: центральные 70%
    w, h = img.size
    crop_percent = settings.osd_crop_percent
    crop_box = (
        int(w * crop_percent),
        int(h * crop_percent),
        int(w * (1 - crop_percent)),
        int(h * (1 - crop_percent)),
    )
    work_img = img.crop(crop_box)

    # 2. Resize до 2048px
    resize_px = settings.osd_resize_px
    work_img.thumbnail((resize_px, resize_px))

    # 3. Grayscale + autocontrast
    work_img = work_img.convert("L")
    work_img = ImageOps.autocontrast(work_img)

    # Сохраняем обработанную версию для OSD (для отладки)
    osd_img_buffer = io.BytesIO()
    work_img.save(osd_img_buffer, format="PNG")
    osd_img_bytes = osd_img_buffer.getvalue()

    # 4. Tesseract OSD
    try:
        osd = pytesseract.image_to_osd(
            work_img,
            config="--psm 0",
            output_type=pytesseract.Output.DICT,
        )
        rotate = osd["rotate"]
        conf = osd["orientation_conf"]
        script = osd.get("script", "unknown")
    except Exception as e:
        rotate = 0
        conf = 0.0
        script = f"error: {e}"

    return {
        "page_num": page_num,
        "rotate": rotate,
        "confidence": conf,
        "script": script,
        "original_size": (w, h),
        "osd_processed_img": osd_img_bytes,  # Изображение которое видел OSD
    }


def apply_rotation(img: Image.Image, rotation: int) -> Image.Image:
    """
    Применяет ОБРАТНЫЙ поворот для коррекции ориентации.

    OSD rotation = угол на который ПОВЁРНУТ текст.
    Коррекция = поворот в ОБРАТНУЮ сторону (-rotation).
    """
    if rotation == 0:
        return img

    # Инвертируем направление: 90 → 270, 270 → 90, 180 → 180
    if rotation == 90:
        return img.transpose(Image.Transpose.ROTATE_270)  # -90° = по часовой
    elif rotation == 180:
        return img.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        return img.transpose(Image.Transpose.ROTATE_90)   # -270° = против часовой
    else:
        return img.rotate(-rotation, expand=True, fillcolor="white")


def process_ocr_single(args: tuple) -> dict:
    """OCR одной страницы с возвратом результата."""
    page_num, img_bytes, lang = args

    img = Image.open(io.BytesIO(img_bytes))
    config = f"--oem {settings.ocr_oem} --psm {settings.ocr_psm}"

    start = time.perf_counter()

    try:
        text = pytesseract.image_to_string(img, lang=lang, config=config)

        # Получаем confidence
        try:
            data = pytesseract.image_to_data(
                img, lang=lang, config=config,
                output_type=pytesseract.Output.DICT
            )
            confidences = [int(c) for c in data["conf"] if isinstance(c, (int, float)) and int(c) >= 0]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        except:
            avg_conf = 0.0

    except Exception as e:
        text = f"ERROR: {e}"
        avg_conf = 0.0

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    return {
        "page_num": page_num,
        "text": text,
        "confidence": avg_conf,
        "time_ms": elapsed_ms,
        "text_length": len(text),
    }


# ============================================================================
# Главный тест
# ============================================================================

def run_debug_pipeline(
    pdf_path: str,
    output_dir: str,
    pages: list[int] = None,
    lang: str = "rus"
):
    """
    Запускает пайплайн OCR с сохранением всех промежуточных этапов.

    Args:
        pdf_path: путь к PDF файлу
        output_dir: папка для сохранения промежуточных результатов
        pages: список страниц для обработки (None = все)
        lang: язык OCR
    """
    from pdf2image import convert_from_path

    output_path = Path(output_dir)

    # Создаём структуру папок
    dirs = {
        "original": output_path / "01_original",
        "osd_input": output_path / "02_osd_input",  # Что видит OSD (обрезанное)
        "rotated": output_path / "03_rotated",
        "final": output_path / "04_final_before_ocr",
    }

    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"🔍 DEBUG PIPELINE TEST")
    print(f"{'='*60}")
    print(f"PDF: {pdf_path}")
    print(f"Output: {output_dir}")
    print(f"Pages: {pages or 'all'}")
    print(f"Lang: {lang}")
    print(f"{'='*60}\n")

    # ========================================================================
    # ЭТАП 1: Split PDF
    # ========================================================================
    print("📄 ЭТАП 1: Разбиение PDF на изображения...")
    start = time.perf_counter()

    # Определяем параметры для convert_from_path
    kwargs = {
        "dpi": settings.render_dpi,
        "fmt": settings.render_format,
        "thread_count": settings.render_thread_count,
    }

    # Если заданы конкретные страницы
    if pages:
        # pdf2image не поддерживает произвольный список,
        # поэтому загружаем все и фильтруем
        all_images = convert_from_path(pdf_path, **kwargs)
        images = [(p, all_images[p-1]) for p in pages if p <= len(all_images)]
    else:
        all_images = convert_from_path(pdf_path, **kwargs)
        images = [(i+1, img) for i, img in enumerate(all_images)]

    split_time = time.perf_counter() - start
    print(f"   ✅ {len(images)} страниц за {split_time:.2f} сек")

    # Сохраняем оригиналы
    print("   💾 Сохранение оригиналов...")
    for page_num, img in images:
        img.save(dirs["original"] / f"page_{page_num:03d}.png")

    # ========================================================================
    # ЭТАП 2: OSD (параллельно)
    # ========================================================================
    print("\n🔄 ЭТАП 2: Определение ориентации (OSD)...")
    start = time.perf_counter()

    # Подготовка задач (конвертируем в bytes для передачи между процессами)
    osd_tasks = []
    for page_num, img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        osd_tasks.append((page_num, buf.getvalue()))

    cpu_count = os.cpu_count() or 4
    osd_results = {}

    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = {executor.submit(process_osd_with_debug, task): task[0] for task in osd_tasks}
        for future in as_completed(futures):
            result = future.result()
            page_num = result["page_num"]
            osd_results[page_num] = result

            # Сохраняем изображение, которое видел OSD
            osd_img = Image.open(io.BytesIO(result["osd_processed_img"]))
            osd_img.save(dirs["osd_input"] / f"page_{page_num:03d}_osd_sees.png")

            rotate = result["rotate"]
            conf = result["confidence"]
            status = f"↻ {rotate}°" if rotate != 0 else "✓"
            print(f"   Страница {page_num}: {status} (conf: {conf:.1f})")

    osd_time = time.perf_counter() - start
    print(f"   ✅ OSD завершён за {osd_time:.2f} сек")

    # ========================================================================
    # ЭТАП 3: Применение поворота
    # ========================================================================
    print("\n🔄 ЭТАП 3: Применение поворота...")

    rotated_images = []
    for page_num, img in images:
        rotation = osd_results[page_num]["rotate"]

        if rotation != 0:
            rotated_img = apply_rotation(img, rotation)
            print(f"   Страница {page_num}: повёрнута на {rotation}°")
        else:
            rotated_img = img
            print(f"   Страница {page_num}: без поворота")

        rotated_images.append((page_num, rotated_img))

        # Сохраняем результат поворота
        rotated_img.save(dirs["rotated"] / f"page_{page_num:03d}_rotated_{rotation}.png")

    # ========================================================================
    # ЭТАП 4: Финальные изображения (перед OCR)
    # ========================================================================
    print("\n💾 ЭТАП 4: Сохранение финальных изображений перед OCR...")

    final_images = []
    for page_num, img in rotated_images:
        # Сохраняем финальное изображение
        img.save(dirs["final"] / f"page_{page_num:03d}_final.png")

        # Конвертируем в bytes для OCR
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        final_images.append((page_num, buf.getvalue()))

    # ========================================================================
    # ЭТАП 5: OCR (параллельно)
    # ========================================================================
    print("\n📝 ЭТАП 5: Распознавание текста (OCR)...")
    start = time.perf_counter()

    ocr_tasks = [(page_num, img_bytes, lang) for page_num, img_bytes in final_images]
    ocr_results = {}

    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = {executor.submit(process_ocr_single, task): task[0] for task in ocr_tasks}
        for future in as_completed(futures):
            result = future.result()
            page_num = result["page_num"]
            ocr_results[page_num] = result

            conf = result["confidence"]
            chars = result["text_length"]
            time_ms = result["time_ms"]
            print(f"   Страница {page_num}: {chars} символов, conf={conf:.1f}%, {time_ms}ms")

    ocr_time = time.perf_counter() - start
    print(f"   ✅ OCR завершён за {ocr_time:.2f} сек")

    # ========================================================================
    # Сохранение сводки
    # ========================================================================
    print("\n📊 Сохранение сводки...")

    summary = {
        "pdf_path": pdf_path,
        "pages_processed": len(images),
        "lang": lang,
        "timings": {
            "split_sec": round(split_time, 2),
            "osd_sec": round(osd_time, 2),
            "ocr_sec": round(ocr_time, 2),
            "total_sec": round(split_time + osd_time + ocr_time, 2),
        },
        "pages": []
    }

    for page_num in sorted(osd_results.keys()):
        osd = osd_results[page_num]
        ocr = ocr_results[page_num]

        page_info = {
            "page_number": page_num,
            "original_size": osd["original_size"],
            "osd": {
                "rotation_detected": osd["rotate"],
                "confidence": osd["confidence"],
                "script": osd["script"],
            },
            "ocr": {
                "text_length": ocr["text_length"],
                "confidence": round(ocr["confidence"], 2),
                "time_ms": ocr["time_ms"],
            },
            "text_preview": ocr["text"][:500] + "..." if len(ocr["text"]) > 500 else ocr["text"],
        }
        summary["pages"].append(page_info)

    # Сохраняем JSON
    with open(output_path / "results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Сохраняем полные тексты
    texts_dir = output_path / "05_ocr_texts"
    texts_dir.mkdir(exist_ok=True)

    for page_num in sorted(ocr_results.keys()):
        text = ocr_results[page_num]["text"]
        with open(texts_dir / f"page_{page_num:03d}.txt", "w", encoding="utf-8") as f:
            f.write(text)

    # ========================================================================
    # Итог
    # ========================================================================
    print(f"\n{'='*60}")
    print(f"✅ ТЕСТ ЗАВЕРШЁН")
    print(f"{'='*60}")
    print(f"Результаты сохранены в: {output_dir}")
    print(f"")
    print(f"📁 Структура папок:")
    print(f"   01_original/        - исходные изображения после split")
    print(f"   02_osd_input/       - что видит OSD (обрезанное, grayscale)")
    print(f"   03_rotated/         - после применения поворота")
    print(f"   04_final_before_ocr/- финальные изображения перед OCR")
    print(f"   05_ocr_texts/       - распознанные тексты")
    print(f"   results.json        - сводка по всем страницам")
    print(f"{'='*60}")

    # Показываем сводку по поворотам
    print(f"\n📋 СВОДКА ПО ПОВОРОТАМ:")
    for page_num in sorted(osd_results.keys()):
        osd = osd_results[page_num]
        ocr = ocr_results[page_num]
        rotation = osd["rotate"]
        osd_conf = osd["confidence"]
        ocr_conf = ocr["confidence"]

        if rotation != 0:
            print(f"   ⚠️  Страница {page_num}: поворот {rotation}° (OSD conf={osd_conf:.1f}), OCR conf={ocr_conf:.1f}%")
        else:
            print(f"   ✓  Страница {page_num}: без поворота (OSD conf={osd_conf:.1f}), OCR conf={ocr_conf:.1f}%")


if __name__ == "__main__":
    # Тестовый PDF
    PDF_PATH = "/Users/mask/Documents/Проекты_2026/FSKDefectPipeline/test_data/input/test_hard.pdf"

    # Папка для вывода
    OUTPUT_DIR = "/Users/mask/Documents/Проекты_2026/tesseract_docker/tests/debug_output"

    # Тестируем те же страницы что и пользователь
    PAGES = [1, 3, 5, 10]

    run_debug_pipeline(
        pdf_path=PDF_PATH,
        output_dir=OUTPUT_DIR,
        pages=PAGES,
        lang="rus"
    )
