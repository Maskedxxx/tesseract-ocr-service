#!/bin/bash
#
# Скрипт запуска OCR Service v2
#
# Единый Docker-контейнер: FastAPI + Tesseract + Poppler.
# Не требует Python или Tesseract на хосте.
#
# Использование:
#   ./start.sh           # Запуск через Docker
#   ./start.sh --build   # Принудительная пересборка образа

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Директория скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     OCR Service v2 - Запуск            ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# === Проверка .env файла ===
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${RED}✗ Файл .env не найден${NC}"
    echo "  Создайте его: cp .env.example .env"
    exit 1
fi
echo -e "${GREEN}✓${NC} Файл .env найден"

# Читаем порт из .env (по умолчанию 8000)
OCR_PORT=$(grep -E "^OCR_PORT=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr -d ' ')
OCR_PORT=${OCR_PORT:-8000}

# === Проверка Docker ===
if ! command -v docker &> /dev/null; then
    echo -e "${RED}✗ Docker не найден${NC}"
    echo "  Установите Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}✗ Docker daemon не запущен${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Docker доступен"
echo ""

# === Запуск ===
echo -e "${YELLOW}Запуск docker-compose (порт ${OCR_PORT})...${NC}"

if [ "$1" = "--build" ]; then
    docker-compose up --build -d
else
    docker-compose up -d
fi

# Ждём запуска сервиса
echo -e "Ожидание готовности сервиса..."
for i in {1..30}; do
    if curl -sf "http://localhost:${OCR_PORT}/health" > /dev/null 2>&1; then
        echo ""
        echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
        echo -e "${GREEN}║     OCR Service v2 запущен!                ║${NC}"
        echo -e "${GREEN}╠════════════════════════════════════════════╣${NC}"
        echo -e "${GREEN}║  URL:    http://localhost:${OCR_PORT}              ║${NC}"
        echo -e "${GREEN}║  Health: http://localhost:${OCR_PORT}/health       ║${NC}"
        echo -e "${GREEN}║  Логи:   docker-compose logs -f           ║${NC}"
        echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
        exit 0
    fi
    sleep 1
    echo -n "."
done

echo ""
echo -e "${RED}✗ Сервис не ответил за 30 секунд${NC}"
echo "  Проверьте логи: docker-compose logs"
exit 1
