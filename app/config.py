"""
Конфигурация Docker API для OCR сервиса.

Все значения читаются из .env файла (или переменных окружения).
Дефолтов нет — .env обязателен для запуска.

Документация по параметрам: .env.example
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Настройки Docker API сервиса.

    Читает переменные с префиксом OCR_ из .env файла.
    """

    model_config = SettingsConfigDict(
        env_prefix="OCR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Игнорируем OCR_WORKER_* переменные
    )

    # URL воркера для проксирования запросов
    worker_url: str

    # Лимиты
    max_file_size_mb: int
    timeout_seconds: float

    # Сервер
    host: str
    port: int


# Глобальный экземпляр настроек
settings = Settings()
