#!/bin/bash
# install.sh  -  Set up rns-map on Ubuntu 22.04 or later
#
# Prerequisites:
#   - rnsd must already be installed and running as a systemd service, OR
#     you are following Scenario B in README.md and setting up rnsd fresh.
#   - Run as the user who will own the service (not root).
#   - sudo access is required to install apt packages and the systemd service.
set -e

# ---------------------------------------------------------------------------
# 1. Install system dependencies
# ---------------------------------------------------------------------------
echo "==> Installing system dependencies"
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-venv \
    python3-dev \
    build-essential \
    gcc

# ---------------------------------------------------------------------------
# 2. Detect Python version and choose compatible aiohttp pin
# ---------------------------------------------------------------------------
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
PYTHON_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")

echo "==> Detected Python ${PYTHON_MAJOR}.${PYTHON_MINOR}"

# aiohttp 3.9.x does not support Python 3.13+
# aiohttp 3.11.x supports Python 3.9 through 3.13
if [ "${PYTHON_MAJOR}" -eq 3 ] && [ "${PYTHON_MINOR}" -ge 13 ]; then
    AIOHTTP_VER="3.11.11"
else
    AIOHTTP_VER="3.9.5"
fi

echo "==> Using aiohttp==${AIOHTTP_VER}"

# ---------------------------------------------------------------------------
# 3. Create Python venv
# ---------------------------------------------------------------------------
echo "==> Creating Python venv"
mkdir -p ~/rns-map/static
python3 -m venv ~/rns-map/venv

# ---------------------------------------------------------------------------
# 4. Install Python packages
# ---------------------------------------------------------------------------
echo "==> Installing Python packages"
~/rns-map/venv/bin/pip install --upgrade pip --quiet
~/rns-map/venv/bin/pip install \
    "rns==1.1.3" \
    "aiohttp==${AIOHTTP_VER}" \
    "msgpack==1.1.2" \
    --quiet

# ---------------------------------------------------------------------------
# 5. Install systemd service
# ---------------------------------------------------------------------------
echo "==> Installing systemd service"
sudo cp ~/rns-map/rns-map.service /etc/systemd/system/rns-map.service
sudo systemctl daemon-reload
sudo systemctl enable rns-map.service

echo ""
echo "Done. Start with:"
echo "  sudo systemctl start rns-map"
echo "  journalctl -u rns-map -f"
echo ""
echo "Then open http://$(hostname -I | awk '{print $1}'):8085 in your browser."
