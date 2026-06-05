#!/usr/bin/env bash
# install_service.sh
# Builds the frontend, then registers and starts Planr as a systemd user
# service. Run from anywhere with your virtualenv active.
# Re-run after moving the project or changing Python/Node paths.

set -euo pipefail

# ── find project directories ──────────────────────────────────────────────────

MAIN_PY=$(find "$HOME" -name main.py -path "*/backend/main.py" 2>/dev/null | head -1)
if [[ -z "$MAIN_PY" ]]; then
    echo "ERROR: Could not find backend/main.py under $HOME"; exit 1
fi

BACKEND_DIR="$(dirname "$MAIN_PY")"
PROJECT_DIR="$(dirname "$BACKEND_DIR")"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo "Backend:  $BACKEND_DIR"
echo "Frontend: $FRONTEND_DIR"

# ── find binaries ──────────────────────────────────────────────────────────────

UVICORN="$(which uvicorn 2>/dev/null || true)"
if [[ -z "$UVICORN" ]]; then
    echo "ERROR: uvicorn not found. Activate your virtualenv first."; exit 1
fi

NPM="$(which npm 2>/dev/null || true)"

# ── build frontend ─────────────────────────────────────────────────────────────

if [[ -d "$FRONTEND_DIR" ]]; then
    if [[ -z "$NPM" ]]; then
        echo ""
        echo "WARNING: npm not found — skipping frontend build."
        echo "         Install Node.js then re-run:"
        echo "           sudo apt install nodejs npm"
        echo "         Or use nvm: https://github.com/nvm-sh/nvm"
        echo ""
    else
        echo "Node: $(node --version)  npm: $(npm --version)"
        echo "Installing frontend dependencies…"
        (cd "$FRONTEND_DIR" && npm install --silent)
        echo "Building frontend…"
        (cd "$FRONTEND_DIR" && npm run build)
        echo "Frontend built → $FRONTEND_DIR/dist/"
        echo ""
    fi
else
    echo "WARNING: $FRONTEND_DIR not found — skipping frontend build."
fi

# ── write systemd service file ─────────────────────────────────────────────────

SERVICE_NAME="planr"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" << UNIT
[Unit]
Description=Planr (FastAPI + React)
After=network.target

[Service]
Type=simple
WorkingDirectory=$BACKEND_DIR
ExecStart=$UVICORN main:app --host 127.0.0.1 --port 8000 --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

# ── enable and start ───────────────────────────────────────────────────────────

systemctl --user daemon-reload
systemctl --user enable  "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

sleep 2
STATUS=$(systemctl --user is-active "$SERVICE_NAME" 2>/dev/null || echo "failed")

echo "Service: $SERVICE_FILE"
echo "Status:  $STATUS"
echo ""
if [[ "$STATUS" == "active" ]]; then
    echo "✓ Planr is running at http://127.0.0.1:8000"
else
    echo "✗ Service did not start."
    echo "  Check: journalctl --user -u $SERVICE_NAME -n 30 --no-pager"
    exit 1
fi

echo ""
echo "Commands:"
echo "  systemctl --user status  $SERVICE_NAME"
echo "  systemctl --user restart $SERVICE_NAME   # after code changes"
echo "  journalctl --user -u $SERVICE_NAME -f    # live logs"
