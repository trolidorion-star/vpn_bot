from typing import Optional

from database.requests import get_setting

import config as app_config


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value or "").strip().lower()
    return s in {"1", "true", "yes", "on"}


def get_split_config_enabled() -> bool:
    # Приоритет: БД -> config.py fallback
    db_value = get_setting("split_config_enabled", None)
    if db_value is not None:
        return _to_bool(db_value)
    return _to_bool(getattr(app_config, "SPLIT_CONFIG_ENABLED", False))


def get_split_config_bind_host() -> str:
    db_value = get_setting("split_config_bind_host", None)
    if db_value:
        return str(db_value).strip()
    return str(getattr(app_config, "SPLIT_CONFIG_BIND_HOST", "0.0.0.0")).strip()


def get_split_config_bind_port() -> int:
    db_value = get_setting("split_config_bind_port", None)
    raw = db_value if db_value is not None else getattr(app_config, "SPLIT_CONFIG_BIND_PORT", 8081)
    try:
        return int(raw)
    except Exception:
        return 8081


def get_split_config_public_base_url() -> str:
    db_value = get_setting("split_config_public_base_url", None)
    if db_value and str(db_value).strip():
        return str(db_value).strip().rstrip("/")
    return str(getattr(app_config, "SPLIT_CONFIG_PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
