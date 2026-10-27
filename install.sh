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
for f in index.html wopr-stats.sh wopr-stats.service wopr-speak.cgi wopr-speak.conf; do
    if [ ! -f "${SRC_DIR}/${f}" ]; then
        echo -e "${RED}ERROR: Missing ${SRC_DIR}/${f}${NC}"
        exit 1
    fi
done

# Check prerequisites
echo -e "${AMBER}[1/8]${NC} Checking prerequisites..."
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

VOICE_DEPS_OK=1
if ! command -v espeak-ng &>/dev/null; then
    echo -e "${AMBER}  espeak-ng not found, installing...${NC}"
    apt-get install -y espeak-ng >/dev/null 2>&1 || VOICE_DEPS_OK=0
fi
if ! command -v fcgiwrap &>/dev/null; then
    echo -e "${AMBER}  fcgiwrap not found, installing...${NC}"
    apt-get install -y fcgiwrap >/dev/null 2>&1 || VOICE_DEPS_OK=0
fi
if [ "$VOICE_DEPS_OK" -eq 1 ] && command -v espeak-ng &>/dev/null && command -v fcgiwrap &>/dev/null; then
    echo -e "  ${GREEN}✓${NC} espeak-ng and fcgiwrap available"
else
    VOICE_DEPS_OK=0
    echo -e "  ${AMBER}!${NC} Could not install espeak-ng/fcgiwrap; JOSHUA voice will be skipped"
fi

# Install dashboard
echo -e "${AMBER}[2/8]${NC} Installing dashboard..."
cp "${SRC_DIR}/index.html" /var/www/html/index.nginx-debian.html
echo -e "  ${GREEN}✓${NC} Dashboard installed to /var/www/html/"

# Install stats script
echo -e "${AMBER}[3/8]${NC} Installing stats gatherer..."
cp "${SRC_DIR}/wopr-stats.sh" /usr/local/bin/wopr-stats.sh
chmod +x /usr/local/bin/wopr-stats.sh
# Fix Windows line endings if present
sed -i 's/\r$//' /usr/local/bin/wopr-stats.sh
echo -e "  ${GREEN}✓${NC} Stats script installed to /usr/local/bin/"

# Create API + data directories and install map data
echo -e "${AMBER}[4/8]${NC} Installing data files..."
mkdir -p /var/www/html/api
mkdir -p /var/www/html/data
if [ -f "${SRC_DIR}/data/ne_110m_land.json" ]; then
    cp "${SRC_DIR}/data/ne_110m_land.json" /var/www/html/data/ne_110m_land.json
    echo -e "  ${GREEN}✓${NC} World map data installed"
else
    echo -e "  ${AMBER}!${NC} Map data not found (map will show grid only)"
fi
if [ -f "${SRC_DIR}/data/country-labels.json" ]; then
    cp "${SRC_DIR}/data/country-labels.json" /var/www/html/data/country-labels.json
fi
echo -e "  ${GREEN}✓${NC} /var/www/html/api/ and /data/ ready"

# Install JOSHUA voice synthesis endpoint (espeak-ng via fcgiwrap)
echo -e "${AMBER}[5/8]${NC} Configuring JOSHUA voice synthesis..."
if [ "$VOICE_DEPS_OK" -eq 1 ]; then
    cp "${SRC_DIR}/wopr-speak.cgi" /usr/local/bin/wopr-speak.cgi
    chmod +x /usr/local/bin/wopr-speak.cgi
    sed -i 's/\r$//' /usr/local/bin/wopr-speak.cgi
    mkdir -p /etc/nginx/snippets
    cp "${SRC_DIR}/wopr-speak.conf" /etc/nginx/snippets/wopr-speak.conf

    NGINX_SITE=""
    for candidate in /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default; do
        if [ -f "$candidate" ]; then NGINX_SITE="$candidate"; break; fi
    done

    if [ -n "$NGINX_SITE" ] && ! grep -q "wopr-speak.conf" "$NGINX_SITE"; then
        cp "$NGINX_SITE" "${NGINX_SITE}.wopr-bak"
        awk '
          { line=$0 }
          { opens=gsub(/\{/,"{"); closes=gsub(/\}/,"}") }
          (!inserted && depth==1 && closes>opens) { print "    include snippets/wopr-speak.conf;"; inserted=1 }
          { depth+=opens-closes; print line }
        ' "$NGINX_SITE" > "${NGINX_SITE}.tmp" && mv "${NGINX_SITE}.tmp" "$NGINX_SITE"

        if nginx -t >/dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} Voice endpoint registered in nginx (backup: ${NGINX_SITE}.wopr-bak)"
        else
            cp "${NGINX_SITE}.wopr-bak" "$NGINX_SITE"
            echo -e "  ${AMBER}!${NC} Automatic nginx edit failed validation and was reverted."
            echo -e "  ${AMBER}!${NC} Add manually inside your server {} block: include snippets/wopr-speak.conf;"
        fi
    elif [ -n "$NGINX_SITE" ]; then
        echo -e "  ${GREEN}✓${NC} Voice endpoint already registered in nginx config"
    else
        echo -e "  ${AMBER}!${NC} Could not locate nginx site config."
        echo -e "  ${AMBER}!${NC} Add manually inside your server {} block: include snippets/wopr-speak.conf;"
    fi

    systemctl enable --now fcgiwrap.socket >/dev/null 2>&1 || systemctl enable --now fcgiwrap >/dev/null 2>&1 || true
    echo -e "  ${GREEN}✓${NC} wopr-speak.cgi installed to /usr/local/bin/"
else
    echo -e "  ${AMBER}!${NC} Skipping voice synthesis setup (missing dependencies)"
fi

# Install systemd service
echo -e "${AMBER}[6/8]${NC} Configuring systemd service..."
cp "${SRC_DIR}/wopr-stats.service" /etc/systemd/system/wopr-stats.service
sed -i 's/\r$//' /etc/systemd/system/wopr-stats.service
systemctl daemon-reload
systemctl enable wopr-stats >/dev/null 2>&1
systemctl restart wopr-stats
echo -e "  ${GREEN}✓${NC} wopr-stats service enabled and started"

# Nginx reload (pick up new /data/ location and voice endpoint)
echo -e "${AMBER}[7/8]${NC} Reloading nginx..."
nginx -t >/dev/null 2>&1 && systemctl reload nginx
echo -e "  ${GREEN}✓${NC} nginx reloaded"

# Verify
echo -e "${AMBER}[8/8]${NC} Verifying installation..."
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
