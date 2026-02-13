"""
Единая конфигурация OCR Service v2.

Объединяет настройки API и Worker в одном классе.
Все значения читаются из .env файла (или переменных окружения).

Единый префикс: OCR_
Документация по параметрам: .env.example
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Настройки OCR Service.

    Читает переменные с префиксом OCR_ из .env файла.
    Объединяет все параметры: API лимиты + параметры обработки.
    """

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Сервер ---
    port: int = 8000

    # --- Авторизация ---
    # Статический API-токен для доступа к сервису
    # Передаётся в заголовке: Authorization: Bearer <token>
    api_token: str

    # --- API: лимиты ---
    max_file_size_mb: int

    # --- Split: PDF -> images ---
    render_dpi: int
    render_thread_count: int
    render_format: str

    # --- OSD: определение ориентации ---
    osd_crop_percent: float
    osd_resize_px: int
    osd_confidence_threshold: float

    # --- Deskew: коррекция наклона ---
    deskew_resize_px: int
    deskew_num_peaks: int
    skew_threshold: float

    # --- OCR: Tesseract ---
    ocr_oem: int
    ocr_psm: int


# Глобальный экземпляр настроек
settings = Settings()
