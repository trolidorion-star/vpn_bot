#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/root/my-private}"
SERVICE_NAME="${2:-yadreno-vpn}"

if [[ ! -d "$APP_DIR" ]]; then
  echo "[ERROR] APP_DIR not found: $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

echo "[1/8] Validate config.py"
python3 - <<'PY'
import importlib.util
from pathlib import Path

cfg_path = Path('config.py')
if not cfg_path.exists():
    raise SystemExit('config.py not found. Copy config.py.example -> config.py first.')

spec = importlib.util.spec_from_file_location('app_config', str(cfg_path))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bot_token = str(getattr(mod, 'BOT_TOKEN', '')).strip()
admin_ids = getattr(mod, 'ADMIN_IDS', [])
placeholder_markers = ('YOUR_', 'PLACEHOLDER', 'TOKEN_BOT', 'TOKEN')

if not bot_token or any(marker in bot_token.upper() for marker in placeholder_markers):
    raise SystemExit('BOT_TOKEN is empty or placeholder in config.py')
if not isinstance(admin_ids, (list, tuple)) or not admin_ids:
    raise SystemExit('ADMIN_IDS is empty in config.py')
print(f'BOT_TOKEN: ok, ADMIN_IDS count: {len(admin_ids)}')
PY

echo "[2/8] Reset critical DB settings to safe defaults"
python3 - <<'PY'
from database.requests import set_setting

safe_defaults = {
    'split_config_enabled': '1',
    'split_config_bind_host': '0.0.0.0',
    'split_config_bind_port': '8081',
    'platega_enabled': '1',
    'platega_test_mode': '0',
    'platega_method_sbp_enabled': '1',
    'platega_method_card_enabled': '1',
    'platega_method_crypto_enabled': '1',
    'legacy_payments_enabled': '1',
}

for key, value in safe_defaults.items():
    set_setting(key, value)

print('Critical settings reset complete')
PY

echo "[3/8] Install/refresh systemd service"
install -m 0644 "$APP_DIR/yadreno-vpn.service" "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "[4/8] Restart bot service"
systemctl restart "$SERVICE_NAME"

if systemctl list-unit-files | grep -q '^x-ui'; then
  echo "[5/8] Restart x-ui"
  systemctl restart x-ui || true
elif command -v x-ui >/dev/null 2>&1; then
  echo "[5/8] Restart x-ui via cli"
  x-ui restart || true
else
  echo "[5/8] x-ui service/cli not found, skip"
fi

echo "[6/8] Open firewall ports (if ufw enabled)"
if command -v ufw >/dev/null 2>&1; then
  ufw allow 80/tcp || true
  ufw allow 443/tcp || true
  ufw allow 8081/tcp || true
  ufw allow 8082/tcp || true
fi

echo "[7/8] Quick health checks"
ss -tulpen | egrep ':443|:8081|:8082' || true
systemctl --no-pager --full status "$SERVICE_NAME" | tail -n 40 || true

echo "[8/8] Done"
echo "Recovery complete. If admin menu is still hidden, verify your Telegram ID is inside ADMIN_IDS in config.py"
