import os
import re
from pathlib import Path
from typing import List

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _to_int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _to_float(value: str | None, default: float) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return default


def _parse_admin_ids(raw: str | None) -> List[int]:
    if not raw:
        return []
    result: List[int] = []
    for part in re.split(r"[,\s;]+", str(raw).strip()):
        if part.isdigit():
            result.append(int(part))
    return result


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_RETURN_URL = os.getenv("BOT_RETURN_URL", "https://t.me/BobrikVPNbot").strip()

ADMIN_IDS = _parse_admin_ids(
    os.getenv("ADMIN_IDS") or os.getenv("BOT_ADMIN_IDS") or os.getenv("MINIAPP_ADMIN_IDS")
)

GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "").strip()
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()
MINI_APP_SHORT_NAME = os.getenv("MINI_APP_SHORT_NAME", "VPN").strip() or "VPN"

DEFAULT_LIMIT_IP = _to_int(os.getenv("DEFAULT_LIMIT_IP"), 2)
DEFAULT_TOTAL_GB = _to_int(os.getenv("DEFAULT_TOTAL_GB"), 1024 * 1024 * 1024 * 1024)
TRAFFIC_THRESHOLD_FOR_KEY_CHANGE = _to_int(os.getenv("TRAFFIC_THRESHOLD_FOR_KEY_CHANGE"), 20)

RATE_LIMITS = {
    "commands_per_minute": _to_int(os.getenv("RATE_LIMIT_COMMANDS_PER_MINUTE"), 30),
    "critical_operations_per_minute": _to_int(
        os.getenv("RATE_LIMIT_CRITICAL_OPERATIONS_PER_MINUTE"), 5
    ),
}

RETRY_CONFIG = {
    "max_attempts": _to_int(os.getenv("RETRY_MAX_ATTEMPTS"), 3),
    "delays": [
        _to_float(os.getenv("RETRY_DELAY_1"), 1.0),
        _to_float(os.getenv("RETRY_DELAY_2"), 3.0),
        _to_float(os.getenv("RETRY_DELAY_3"), 9.0),
    ],
}

SPLIT_CONFIG_ENABLED = _to_bool(os.getenv("SPLIT_CONFIG_ENABLED"), False)
SPLIT_CONFIG_BIND_HOST = os.getenv("SPLIT_CONFIG_BIND_HOST", "0.0.0.0").strip() or "0.0.0.0"
SPLIT_CONFIG_BIND_PORT = _to_int(os.getenv("SPLIT_CONFIG_BIND_PORT"), 8081)
SPLIT_CONFIG_PUBLIC_BASE_URL = os.getenv("SPLIT_CONFIG_PUBLIC_BASE_URL", "").strip()
