#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install_systemd_service.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="$(command -v python3)"
SERVICE_NAME="yadreno-vpn"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "python3 not found"
  exit 1
fi

cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Yadreno VPN Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_BIN} ${PROJECT_DIR}/main.py
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "Service installed: ${SERVICE_NAME}"
echo "Check status:"
echo "  systemctl status ${SERVICE_NAME} --no-pager"
echo "Follow logs:"
echo "  journalctl -u ${SERVICE_NAME} -f"
