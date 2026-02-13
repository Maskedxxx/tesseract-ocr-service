"""
In-memory хранилище координат документов.

Временное решение для хранения координат слов/строк/блоков,
полученных при OCR. Координаты используются фронтендом для
подсветки текста в документе.

Особенности:
    - Хранение в памяти (без персистентности)
    - Связь с документом через UUID
    - Пока без TTL и лимитов (будет добавлено позже)
"""

import logging
import uuid
from datetime import datetime
from typing import Optional

from ocr.schemas import DocumentCoordinates, PageCoordinates

logger = logging.getLogger(__name__)

# In-memory хранилище: {doc_id: DocumentCoordinates}
_store: dict[str, DocumentCoordinates] = {}


def save_coordinates(pages: list[PageCoordinates]) -> str:
    """
    Сохраняет координаты документа в хранилище.

    Генерирует уникальный UUID для документа и сохраняет
    все координаты страниц.

    Args:
        pages: список страниц с координатами (PageCoordinates)

    Returns:
        str: UUID документа для последующего запроса координат
    """
    doc_id = str(uuid.uuid4())

    # Создаём запись документа
    document = DocumentCoordinates(
        doc_id=doc_id,
        created_at=datetime.now(),
        pages=pages,
    )

    # Сохраняем в хранилище
    _store[doc_id] = document

    logger.info(
        f"Сохранены координаты: doc_id={doc_id}, "
        f"страниц={len(pages)}, "
        f"всего в хранилище={len(_store)}"
    )

    return doc_id


def get_coordinates(doc_id: str) -> Optional[DocumentCoordinates]:
    """
    Получает координаты документа по его UUID.

    Args:
        doc_id: UUID документа

    Returns:
        DocumentCoordinates или None если документ не найден
    """
    document = _store.get(doc_id)

    if document:
        logger.debug(f"Найден документ: {doc_id}")
    else:
        logger.warning(f"Документ не найден: {doc_id}")

    return document


def get_store_stats() -> dict:
    """
    Возвращает статистику хранилища.

    Полезно для мониторинга и отладки.

    Returns:
        dict: {documents_count, oldest_doc, newest_doc}
    """
    if not _store:
        return {
            "documents_count": 0,
            "oldest_doc": None,
            "newest_doc": None,
        }

    # Сортируем по времени создания
    sorted_docs = sorted(_store.values(), key=lambda d: d.created_at)

    return {
        "documents_count": len(_store),
        "oldest_doc": {
            "doc_id": sorted_docs[0].doc_id,
            "created_at": sorted_docs[0].created_at.isoformat(),
        },
        "newest_doc": {
            "doc_id": sorted_docs[-1].doc_id,
            "created_at": sorted_docs[-1].created_at.isoformat(),
        },
    }
