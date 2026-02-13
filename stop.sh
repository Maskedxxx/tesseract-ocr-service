#!/bin/bash
#
# Скрипт остановки OCR Service v2
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

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     OCR Service v2 - Остановка         ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Остановка Docker
echo -e "${YELLOW}Остановка контейнера...${NC}"

if docker-compose ps -q 2>/dev/null | grep -q .; then
    docker-compose down
    echo -e "${GREEN}✓${NC} Контейнер остановлен"
else
    echo -e "${GREEN}✓${NC} Контейнер не был запущен"
fi

echo ""
echo -e "${GREEN}OCR Service остановлен${NC}"
