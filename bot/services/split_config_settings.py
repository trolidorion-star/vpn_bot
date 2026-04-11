import os
from typing import Iterable, Optional

import config as app_config
from database.requests import get_setting


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value or "").strip().lower()
    return s in {"1", "true", "yes", "on", "y"}


def _first_non_empty_from_config(attr_names: Iterable[str]) -> Optional[object]:
    for name in attr_names:
        if hasattr(app_config, name):
            value = getattr(app_config, name)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return None


def _first_non_empty_from_env(env_names: Iterable[str]) -> Optional[str]:
    for name in env_names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _safe_get_setting(key: str, default=None):
    try:
        return get_setting(key, default)
    except Exception:
        return default


def get_split_config_enabled() -> bool:
    config_value = _first_non_empty_from_config(
        ("SPLIT_CONFIG_ENABLED", "split_config_enabled", "SPLIT_ENABLED")
    )
    if config_value is not None:
        return _to_bool(config_value)

    env_value = _first_non_empty_from_env(
        ("SPLIT_CONFIG_ENABLED", "split_config_enabled", "SPLIT_ENABLED")
    )
    if env_value is not None:
        return _to_bool(env_value)

    db_value = _safe_get_setting("split_config_enabled", None)
    if db_value is not None:
        return _to_bool(db_value)

    return False


def get_split_config_bind_host() -> str:
    config_value = _first_non_empty_from_config(
        ("SPLIT_CONFIG_BIND_HOST", "split_config_bind_host", "SPLIT_BIND_HOST")
    )
    if config_value is not None:
        return str(config_value).strip()

    env_value = _first_non_empty_from_env(
        ("SPLIT_CONFIG_BIND_HOST", "split_config_bind_host", "SPLIT_BIND_HOST")
    )
    if env_value is not None:
        return env_value

    db_value = _safe_get_setting("split_config_bind_host", None)
    if db_value:
        return str(db_value).strip()

    return "0.0.0.0"


def get_split_config_bind_port() -> int:
    raw = _first_non_empty_from_config(
        ("SPLIT_CONFIG_BIND_PORT", "split_config_bind_port", "SPLIT_BIND_PORT")
    )
    if raw is None:
        raw = _first_non_empty_from_env(
            ("SPLIT_CONFIG_BIND_PORT", "split_config_bind_port", "SPLIT_BIND_PORT")
        )
    if raw is None:
        raw = _safe_get_setting("split_config_bind_port", None)
    if raw is None:
        raw = 8081

    try:
        return int(raw)
    except Exception:
        return 8081


def get_split_config_public_base_url() -> str:
    config_value = _first_non_empty_from_config(
        ("SPLIT_CONFIG_PUBLIC_BASE_URL", "split_config_public_base_url", "SPLIT_PUBLIC_BASE_URL")
    )
    if config_value is not None:
        return str(config_value).strip().rstrip("/")

    env_value = _first_non_empty_from_env(
        ("SPLIT_CONFIG_PUBLIC_BASE_URL", "split_config_public_base_url", "SPLIT_PUBLIC_BASE_URL")
    )
    if env_value is not None:
        return env_value.rstrip("/")

    db_value = _safe_get_setting("split_config_public_base_url", None)
    return str(db_value or "").strip().rstrip("/")


def get_split_config_public_url(token: str) -> str:
    base = get_split_config_public_base_url()
    if not base:
        return ""
    return f"{base}/split/{token}.json"


def is_split_config_ready() -> bool:
    return bool(get_split_config_public_base_url())
