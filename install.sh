#!/bin/bash
# ============================================================
# WOPR Dashboard Installer
# Installs the War Games-inspired nginx dashboard on a Raspberry Pi
# https://github.com/dougrichards13/nginx_WOPR
# ============================================================
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
AMBER='\033[0;33m'
NC='\033[0m'

echo -e "${GREEN}"
echo "  ██╗    ██╗ ██████╗ ██████╗ ██████╗ "
echo "  ██║    ██║██╔═══██╗██╔══██╗██╔══██╗"
echo "  ██║ █╗ ██║██║   ██║██████╔╝██████╔╝"
echo "  ██║███╗██║██║   ██║██╔═══╝ ██╔══██╗"
echo "  ╚███╔███╔╝╚██████╔╝██║     ██║  ██║"
echo "   ╚══╝╚══╝  ╚═════╝ ╚═╝     ╚═╝  ╚═╝"
echo -e "${NC}"
echo "  WOPR Dashboard Installer"
echo "  ========================"
echo ""

# Must be root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}ERROR: This script must be run as root (use sudo)${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/src"

# Verify source files exist
for f in index.html wopr-stats.sh wopr-stats.service; do
    if [ ! -f "${SRC_DIR}/${f}" ]; then
        echo -e "${RED}ERROR: Missing ${SRC_DIR}/${f}${NC}"
        exit 1
    fi
done

# Check prerequisites
echo -e "${AMBER}[1/7]${NC} Checking prerequisites..."
if ! command -v nginx &>/dev/null; then
    echo -e "${RED}  nginx not found. Install with: sudo apt install nginx${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} nginx found"

if ! command -v bc &>/dev/null; then
    echo -e "${AMBER}  bc not found, installing...${NC}"
    apt-get install -y bc >/dev/null 2>&1
fi
echo -e "  ${GREEN}✓${NC} bc available"

# Install dashboard
echo -e "${AMBER}[2/7]${NC} Installing dashboard..."
cp "${SRC_DIR}/index.html" /var/www/html/index.nginx-debian.html
echo -e "  ${GREEN}✓${NC} Dashboard installed to /var/www/html/"

# Install stats script
echo -e "${AMBER}[3/7]${NC} Installing stats gatherer..."
cp "${SRC_DIR}/wopr-stats.sh" /usr/local/bin/wopr-stats.sh
chmod +x /usr/local/bin/wopr-stats.sh
# Fix Windows line endings if present
sed -i 's/\r$//' /usr/local/bin/wopr-stats.sh
echo -e "  ${GREEN}✓${NC} Stats script installed to /usr/local/bin/"

# Create API + data directories and install map data
echo -e "${AMBER}[4/7]${NC} Installing data files..."
mkdir -p /var/www/html/api
mkdir -p /var/www/html/data
if [ -f "${SRC_DIR}/data/ne_110m_land.json" ]; then
    cp "${SRC_DIR}/data/ne_110m_land.json" /var/www/html/data/ne_110m_land.json
    echo -e "  ${GREEN}✓${NC} World map data installed"
else
    echo -e "  ${AMBER}!${NC} Map data not found (map will show grid only)"
fi
echo -e "  ${GREEN}✓${NC} /var/www/html/api/ and /data/ ready"

# Install systemd service
echo -e "${AMBER}[5/7]${NC} Configuring systemd service..."
cp "${SRC_DIR}/wopr-stats.service" /etc/systemd/system/wopr-stats.service
sed -i 's/\r$//' /etc/systemd/system/wopr-stats.service
systemctl daemon-reload
systemctl enable wopr-stats >/dev/null 2>&1
systemctl restart wopr-stats
echo -e "  ${GREEN}✓${NC} wopr-stats service enabled and started"

# Nginx reload (pick up new /data/ location)
echo -e "${AMBER}[6/7]${NC} Reloading nginx..."
nginx -t >/dev/null 2>&1 && systemctl reload nginx
echo -e "  ${GREEN}✓${NC} nginx reloaded"

# Verify
echo -e "${AMBER}[7/7]${NC} Verifying installation..."
sleep 3
if systemctl is-active --quiet wopr-stats; then
    echo -e "  ${GREEN}✓${NC} wopr-stats service is running"
else
    echo -e "  ${RED}✗${NC} wopr-stats service failed to start"
    echo "  Check logs with: journalctl -u wopr-stats -n 20"
fi

if [ -f /var/www/html/api/stats.json ]; then
    echo -e "  ${GREEN}✓${NC} stats.json is being generated"
else
    echo -e "  ${AMBER}!${NC} stats.json not yet created (may need a few seconds)"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo -e "${GREEN}  WOPR DASHBOARD INSTALLED SUCCESSFULLY${NC}"
echo -e "${GREEN}════════════════════════════════════════════${NC}"
echo ""
echo -e "  Open in browser: ${AMBER}http://${IP}/${NC}"
echo ""
echo -e "  Manage service:"
echo -e "    systemctl status wopr-stats"
echo -e "    systemctl restart wopr-stats"
echo -e "    journalctl -u wopr-stats -f"
echo ""
echo -e "  ${GREEN}\"Shall we play a game?\"${NC}"
