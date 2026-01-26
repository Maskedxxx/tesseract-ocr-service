#!/bin/bash
#
# Скрипт запуска OCR Service
#
# Выполняет:
#   1. Проверяет зависимости (python, tesseract, poppler)
#   2. Запускает OCR Worker на хосте в фоне
#   3. Ждёт готовности Worker
#   4. Запускает Docker API
#
# Использование:
#   ./start.sh          # Запуск всего стека
#   ./start.sh --local  # Запуск без Docker (оба на хосте)

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

# Файл для PID воркера
WORKER_PID_FILE="$SCRIPT_DIR/.worker.pid"
WORKER_LOG_FILE="$SCRIPT_DIR/worker.log"

# Порты
WORKER_PORT=8001
API_PORT=8000

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       OCR Service - Запуск             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# === Проверка зависимостей ===
echo -e "${YELLOW}[1/4] Проверка зависимостей...${NC}"

# Python
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}✗ Python не найден${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python: $($PYTHON_CMD --version)"

# Tesseract
if ! command -v tesseract &> /dev/null; then
    echo -e "${RED}✗ Tesseract не найден${NC}"
    echo "  Установите: brew install tesseract tesseract-lang"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Tesseract: $(tesseract --version 2>&1 | head -1)"

# Poppler (pdftoppm)
if ! command -v pdftoppm &> /dev/null; then
    echo -e "${RED}✗ Poppler (pdftoppm) не найден${NC}"
    echo "  Установите: brew install poppler"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Poppler: $(pdftoppm -v 2>&1 | head -1)"

# Python модули
$PYTHON_CMD -c "import fastapi, uvicorn, pdf2image, pytesseract, deskew" 2>/dev/null || {
    echo -e "${RED}✗ Не все Python модули установлены${NC}"
    echo "  Выполните: pip install -r requirements.txt"
    exit 1
}
echo -e "  ${GREEN}✓${NC} Python модули установлены"
echo ""

# === Проверка, не запущен ли уже Worker ===
echo -e "${YELLOW}[2/4] Проверка портов...${NC}"

if lsof -i :$WORKER_PORT &> /dev/null; then
    echo -e "  ${YELLOW}⚠${NC} Порт $WORKER_PORT уже занят"

    # Проверяем, это наш Worker?
    if curl -s http://localhost:$WORKER_PORT/health | grep -q "ocr-worker"; then
        echo -e "  ${GREEN}✓${NC} OCR Worker уже запущен"
        WORKER_ALREADY_RUNNING=true
    else
        echo -e "${RED}✗ Порт $WORKER_PORT занят другим процессом${NC}"
        exit 1
    fi
else
    echo -e "  ${GREEN}✓${NC} Порт $WORKER_PORT свободен"
    WORKER_ALREADY_RUNNING=false
fi

if lsof -i :$API_PORT &> /dev/null; then
    echo -e "  ${YELLOW}⚠${NC} Порт $API_PORT уже занят"
else
    echo -e "  ${GREEN}✓${NC} Порт $API_PORT свободен"
fi
echo ""

# === Запуск OCR Worker ===
echo -e "${YELLOW}[3/4] Запуск OCR Worker...${NC}"

if [ "$WORKER_ALREADY_RUNNING" = true ]; then
    echo -e "  ${GREEN}✓${NC} Worker уже работает"
else
    # Запускаем Worker в фоне
    echo -e "  Запуск Worker на порту $WORKER_PORT..."

    nohup $PYTHON_CMD -m ocr_worker.main > "$WORKER_LOG_FILE" 2>&1 &
    WORKER_PID=$!
    echo $WORKER_PID > "$WORKER_PID_FILE"

    # Ждём готовности Worker (до 30 секунд)
    echo -e "  Ожидание готовности Worker..."
    for i in {1..30}; do
        if curl -s http://localhost:$WORKER_PORT/health &> /dev/null; then
            echo -e "  ${GREEN}✓${NC} Worker запущен (PID: $WORKER_PID)"
            break
        fi

        # Проверяем, не упал ли процесс
        if ! kill -0 $WORKER_PID 2>/dev/null; then
            echo -e "${RED}✗ Worker упал при запуске${NC}"
            echo "  Логи: $WORKER_LOG_FILE"
            tail -20 "$WORKER_LOG_FILE"
            exit 1
        fi

        sleep 1
        echo -n "."
    done
    echo ""

    # Финальная проверка
    if ! curl -s http://localhost:$WORKER_PORT/health &> /dev/null; then
        echo -e "${RED}✗ Worker не отвечает после 30 секунд${NC}"
        echo "  Логи: $WORKER_LOG_FILE"
        exit 1
    fi
fi
echo ""

# === Запуск Docker API или локального API ===
echo -e "${YELLOW}[4/4] Запуск API...${NC}"

if [ "$1" = "--local" ]; then
    # Локальный режим — запускаем API без Docker
    echo -e "  Режим: локальный (без Docker)"
    echo -e "  Запуск API на порту $API_PORT..."

    # Устанавливаем URL воркера на localhost
    export OCR_WORKER_URL="http://localhost:$WORKER_PORT"

    # Запускаем API
    $PYTHON_CMD -m uvicorn app.main:app --host 0.0.0.0 --port $API_PORT
else
    # Docker режим
    echo -e "  Режим: Docker"

    # Проверяем Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}✗ Docker не найден${NC}"
        echo "  Используйте: ./start.sh --local"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        echo -e "${RED}✗ Docker daemon не запущен${NC}"
        exit 1
    fi

    echo -e "  Запуск docker-compose..."
    docker-compose up --build
fi
