#!/usr/bin/env bash
# ============================================================
# setup_vps.sh — One-shot setup / update script for the
# Telegram Notice Bot on an Ubuntu VPS.
#
# Run this as a user who has sudo access:
#   bash setup_vps.sh
#
# Safe to re-run any time (git pull + reinstall + restart).
# ============================================================
set -euo pipefail

# ---- config -------------------------------------------------
SERVICE_NAME="telegram-notice-bot"
DEPLOY_DIR="/opt/telegram-notice-bot"
VENV="$DEPLOY_DIR/venv"
PYTHON="$VENV/bin/python3"
PIP="$VENV/bin/pip"
# -------------------------------------------------------------

echo ""
echo "========================================================"
echo " Telegram Notice Bot — VPS setup / update"
echo "========================================================"
echo ""

# 1. Pull latest code
echo "[1/5] Pulling latest code from GitHub..."
cd "$DEPLOY_DIR"
git fetch origin
git reset --hard origin/main
echo "      Done. Current commit: $(git rev-parse --short HEAD)"
echo ""

# 2. Create venv if missing
if [ ! -f "$PYTHON" ]; then
    echo "[2/5] Creating Python virtual environment..."
    python3 -m venv "$VENV"
else
    echo "[2/5] Python virtual environment already exists — skipping."
fi
echo ""

# 3. Install / upgrade Python packages
echo "[3/5] Installing Python packages (requirements.txt)..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r requirements.txt --quiet
echo "      Done."
echo ""

# 4. Install Playwright Chromium + ALL OS-level system libraries
#    --with-deps calls apt-get to install libnss3, libatk, libgbm, etc.
#    Without this step Chromium silently fails to launch on a fresh VPS.
echo "[4/5] Installing Playwright Chromium + system dependencies..."
echo "      (This needs sudo for apt-get — you may be prompted for a password)"
sudo "$PYTHON" -m playwright install --with-deps chromium
echo "      Done."
echo ""

# 5. Restart systemd service (or start it if it was never enabled)
echo "[5/5] Restarting $SERVICE_NAME service..."
# Ensure logs directory exists (unit file writes there)
mkdir -p "$DEPLOY_DIR/logs"
# Reload unit files in case the .service file changed
sudo systemctl daemon-reload
if sudo systemctl is-enabled --quiet "$SERVICE_NAME" 2>/dev/null; then
    sudo systemctl restart "$SERVICE_NAME"
else
    sudo cp "$DEPLOY_DIR/telegram-notice-bot.service" \
            "/etc/systemd/system/$SERVICE_NAME.service"
    sudo systemctl daemon-reload
    sudo systemctl enable --now "$SERVICE_NAME"
fi
echo "      Done."
echo ""

echo "========================================================"
echo " Setup complete! Tailing logs (Ctrl+C to stop)..."
echo "========================================================"
echo ""
sleep 2
sudo journalctl -u "$SERVICE_NAME" -n 60 --no-pager
echo ""
echo "Follow live: sudo journalctl -u $SERVICE_NAME -f"
