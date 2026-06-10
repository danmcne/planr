#!/usr/bin/env bash
# install.sh — planr v1.1.0
set -euo pipefail

PLANR_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "planr — install"
echo "───────────────────────────────────────────────"
echo ""
echo "Python environment:"
echo "  1) Create virtual environment in .venv/  (recommended)"
echo "  2) Use system / global Python             (no venv)"
echo ""
printf "Choice [1]: "; read -r choice; choice="${choice:-1}"

if [ "$choice" = "2" ]; then
    echo "→ Installing into global Python…"
    python3 -m pip install --user -q -r "$PLANR_DIR/requirements.txt"
    PYTHON_BIN="python3"
    # Try common uvicorn locations
    if   command -v uvicorn   &>/dev/null; then UVICORN_BIN="uvicorn"
    elif python3 -m uvicorn --version &>/dev/null 2>&1; then UVICORN_BIN="python3 -m uvicorn"
    else
        echo "✗  uvicorn not found after install. Run: pip3 install --user uvicorn"
        exit 1
    fi
    EXEC_START="$UVICORN_BIN main:app --host 127.0.0.1 --port 7000"
else
    VENV="$PLANR_DIR/.venv"
    echo "→ Creating virtual environment in $VENV …"
    python3 -m venv "$VENV"
    echo "→ Installing dependencies…"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$PLANR_DIR/requirements.txt"
    EXEC_START="$VENV/bin/uvicorn main:app --host 127.0.0.1 --port 7000"
fi

# Install systemd user service
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_DIR/planr.service" << SVCEOF
[Unit]
Description=planr — personal information manager
After=network.target

[Service]
Type=simple
WorkingDirectory=$PLANR_DIR
ExecStart=$EXEC_START
Restart=on-failure
RestartSec=3

Environment=PLANR_DB=%h/.planr/planr.db
Environment=PLANR_NOTES_DIR=%h/.planr/notes
Environment=PLANR_JOURNAL_DIR=%h/.planr/journal

[Install]
WantedBy=default.target
SVCEOF

systemctl --user daemon-reload
systemctl --user enable --now planr.service

echo ""
echo "✓  planr is running at http://127.0.0.1:7000"
echo "   Logs:    journalctl --user -u planr -f"
echo "   Stop:    systemctl --user stop planr"
echo "   Restart: systemctl --user restart planr"
echo ""
