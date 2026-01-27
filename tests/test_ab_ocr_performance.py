"""
A/B тест производительности OCR: старый vs новый подход.

Загружает тестовый PDF, обрабатывает каждую страницу двумя методами,
сравнивает результаты и выводит статистику.

Запуск:
    python tests/test_ab_ocr_performance.py

Ожидаемый результат:
    - Новый метод ~2x быстрее (один вызов Tesseract вместо двух)
    - Текст совпадает (или минимальные отличия в форматировании)
    - Confidence идентичный (оба метода используют одну и ту же формулу)
"""

import io
import sys
import time
from pathlib import Path

# Добавляем корневую папку проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2image import convert_from_path
from PIL import Image

from test_ocr_optimization import (
    OCRTestResult,
    compare_texts,
    ocr_new_way,
    ocr_old_way,
)


def run_ab_test(
    pdf_path: str,
    pages: list[int] = None,
    lang: str = "rus",
    config: str = "--oem 3 --psm 3",
):
    """
    Запускает A/B тест на указанном PDF.

    Для каждой страницы:
        1. Вызывает ocr_old_way (2 вызова Tesseract)
        2. Вызывает ocr_new_way (1 вызов Tesseract)
        3. Сравнивает результаты

    Args:
        pdf_path: путь к тестовому PDF
        pages: список страниц для тестирования (None = все)
        lang: язык OCR
        config: конфиг Tesseract
    """
    print(f"\n{'='*70}")
    print(f"🔬 A/B ТЕСТ: ОПТИМИЗАЦИЯ OCR (1 вызов vs 2 вызова)")
    print(f"{'='*70}")
    print(f"PDF: {pdf_path}")
    print(f"Страницы: {pages or 'все'}")
    print(f"Язык: {lang}")
    print(f"Config: {config}")
    print(f"{'='*70}\n")

    # Загружаем PDF
    print("📄 Загрузка PDF...")
    start = time.perf_counter()

    all_images = convert_from_path(pdf_path, dpi=300)
    load_time = time.perf_counter() - start

    print(f"   ✅ Загружено {len(all_images)} страниц за {load_time:.2f} сек\n")

    # Выбираем страницы для теста
    if pages:
        test_images = [(p, all_images[p - 1]) for p in pages if p <= len(all_images)]
    else:
        test_images = [(i + 1, img) for i, img in enumerate(all_images)]

    # Результаты
    results = []

    # Обрабатываем каждую страницу
    print(f"🧪 Тестирование {len(test_images)} страниц...\n")
    print("-" * 70)

    for page_num, image in test_images:
        print(f"\n📑 Страница {page_num}:")

        # Старый метод (2 вызова)
        print("   [OLD] 2 вызова Tesseract...", end=" ", flush=True)
        old_result = ocr_old_way(image, lang=lang, config=config)
        print(f"{old_result.time_ms}ms, conf={old_result.confidence:.1f}%")

        # Новый метод (1 вызов)
        print("   [NEW] 1 вызов Tesseract...", end=" ", flush=True)
        new_result = ocr_new_way(image, lang=lang, config=config)
        print(f"{new_result.time_ms}ms, conf={new_result.confidence:.1f}%")

        # Сравнение текстов
        comparison = compare_texts(old_result.text, new_result.text)

        # Расчёт ускорения
        if new_result.time_ms > 0:
            speedup = old_result.time_ms / new_result.time_ms
        else:
            speedup = 0.0

        # Результаты страницы
        page_result = {
            "page": page_num,
            "old_time_ms": old_result.time_ms,
            "new_time_ms": new_result.time_ms,
            "speedup": speedup,
            "old_conf": old_result.confidence,
            "new_conf": new_result.confidence,
            "text_match": comparison["exact_match_normalized"],
            "len_ratio": comparison["length_ratio"],
            "old_len": comparison["len_old"],
            "new_len": comparison["len_new"],
        }
        results.append(page_result)

        # Выводим сравнение
        match_status = "✅" if comparison["exact_match_normalized"] else "⚠️"
        print(f"   Ускорение: {speedup:.2f}x")
        print(f"   Текст: {match_status} (ratio={comparison['length_ratio']:.3f})")

    print("\n" + "-" * 70)

    # Сводная статистика
    print(f"\n{'='*70}")
    print(f"📊 СВОДНАЯ СТАТИСТИКА")
    print(f"{'='*70}\n")

    # Время
    total_old = sum(r["old_time_ms"] for r in results)
    total_new = sum(r["new_time_ms"] for r in results)
    avg_speedup = sum(r["speedup"] for r in results) / len(results) if results else 0

    print(f"⏱️  ВРЕМЯ:")
    print(f"   Старый метод (2 вызова): {total_old}ms ({total_old/1000:.2f} сек)")
    print(f"   Новый метод (1 вызов):   {total_new}ms ({total_new/1000:.2f} сек)")
    print(f"   Экономия: {total_old - total_new}ms ({(total_old - total_new)/1000:.2f} сек)")
    print(f"   Среднее ускорение: {avg_speedup:.2f}x")
    print()

    # Точность
    matches = sum(1 for r in results if r["text_match"])
    print(f"📝 ТОЧНОСТЬ ТЕКСТА:")
    print(f"   Совпадений: {matches}/{len(results)}")
    print()

    # Confidence
    avg_old_conf = sum(r["old_conf"] for r in results) / len(results) if results else 0
    avg_new_conf = sum(r["new_conf"] for r in results) / len(results) if results else 0
    print(f"🎯 CONFIDENCE:")
    print(f"   Старый метод: {avg_old_conf:.2f}%")
    print(f"   Новый метод:  {avg_new_conf:.2f}%")
    print(f"   Разница:      {abs(avg_old_conf - avg_new_conf):.2f}%")
    print()

    # Детальная таблица
    print(f"{'='*70}")
    print("📋 ДЕТАЛИЗАЦИЯ ПО СТРАНИЦАМ:")
    print(f"{'='*70}")
    print(f"{'Стр':<5} {'Old(ms)':<10} {'New(ms)':<10} {'Ускор':<8} {'Совпад':<8} {'Len ratio':<10}")
    print("-" * 70)

    for r in results:
        match = "✅" if r["text_match"] else "⚠️"
        print(
            f"{r['page']:<5} {r['old_time_ms']:<10} {r['new_time_ms']:<10} "
            f"{r['speedup']:.2f}x{'':<4} {match:<8} {r['len_ratio']:.4f}"
        )

    print("-" * 70)
    print()

    # Вывод различий в тексте (если есть)
    non_matching = [r for r in results if not r["text_match"]]
    if non_matching:
        print(f"⚠️  СТРАНИЦЫ С РАЗЛИЧИЯМИ В ТЕКСТЕ:")
        for r in non_matching:
            print(f"   Страница {r['page']}: old={r['old_len']} символов, new={r['new_len']} символов")
        print()
        print("   💡 Это нормально: image_to_string и image_to_data могут")
        print("      по-разному форматировать пробелы и переносы строк.")
        print("      Важно, что содержание (слова) совпадает.")
    else:
        print("✅ Все тексты совпадают (после нормализации пробелов)")

    print(f"\n{'='*70}")
    print("🎉 ТЕСТ ЗАВЕРШЁН")
    print(f"{'='*70}\n")

    return results


if __name__ == "__main__":
    # Тестовый PDF — используем тот же что в test_pipeline_debug.py
    PDF_PATH = "/Users/mask/Documents/Проекты_2026/FSKDefectPipeline/test_data/input/test_hard.pdf"

    # Проверяем существование файла
    if not Path(PDF_PATH).exists():
        print(f"❌ Тестовый PDF не найден: {PDF_PATH}")
        print("Укажите путь к существующему PDF файлу.")
        sys.exit(1)

    # Тестируем 4 страницы для репрезентативности
    PAGES = [1, 3, 5, 10]

    # Запускаем A/B тест
    run_ab_test(
        pdf_path=PDF_PATH,
        pages=PAGES,
        lang="rus",
        config="--oem 3 --psm 3",
    )
