#!/bin/bash
#
# Скрипт остановки OCR Service
#
# Останавливает:
#   1. Docker API (если запущен)
#   2. OCR Worker на хосте
#
# Использование:
#   ./stop.sh

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Директория скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Файл для PID воркера
WORKER_PID_FILE="$SCRIPT_DIR/.worker.pid"

# Порты
WORKER_PORT=8001
API_PORT=8000

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       OCR Service - Остановка          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# === Остановка Docker ===
echo -e "${YELLOW}[1/2] Остановка Docker API...${NC}"

if docker-compose ps 2>/dev/null | grep -q "ocr-api"; then
    docker-compose down
    echo -e "  ${GREEN}✓${NC} Docker контейнер остановлен"
else
    echo -e "  ${GREEN}✓${NC} Docker контейнер не был запущен"
fi
echo ""

# === Остановка OCR Worker ===
echo -e "${YELLOW}[2/2] Остановка OCR Worker...${NC}"

# Способ 1: через PID файл
if [ -f "$WORKER_PID_FILE" ]; then
    WORKER_PID=$(cat "$WORKER_PID_FILE")

    if kill -0 $WORKER_PID 2>/dev/null; then
        echo -e "  Остановка Worker (PID: $WORKER_PID)..."
        kill $WORKER_PID

        # Ждём завершения
        for i in {1..10}; do
            if ! kill -0 $WORKER_PID 2>/dev/null; then
                break
            fi
            sleep 0.5
        done

        # Если всё ещё работает — kill -9
        if kill -0 $WORKER_PID 2>/dev/null; then
            kill -9 $WORKER_PID 2>/dev/null || true
        fi

        echo -e "  ${GREEN}✓${NC} Worker остановлен"
    else
        echo -e "  ${GREEN}✓${NC} Worker уже был остановлен"
    fi

    rm -f "$WORKER_PID_FILE"
else
    # Способ 2: через порт
    if lsof -i :$WORKER_PORT &> /dev/null; then
        echo -e "  Поиск процесса на порту $WORKER_PORT..."

        # Получаем PID процесса на порту
        WORKER_PID=$(lsof -ti :$WORKER_PORT 2>/dev/null || true)

        if [ -n "$WORKER_PID" ]; then
            echo -e "  Остановка Worker (PID: $WORKER_PID)..."
            kill $WORKER_PID 2>/dev/null || true
            sleep 1
            kill -9 $WORKER_PID 2>/dev/null || true
            echo -e "  ${GREEN}✓${NC} Worker остановлен"
        fi
    else
        echo -e "  ${GREEN}✓${NC} Worker не был запущен"
    fi
fi

echo ""
echo -e "${GREEN}OCR Service полностью остановлен${NC}"
