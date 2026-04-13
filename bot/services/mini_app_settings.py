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


def get_mini_app_enabled() -> bool:
    config_value = _first_non_empty_from_config(
        ("MINI_APP_ENABLED", "mini_app_enabled", "MINIAPP_ENABLED")
    )
    if config_value is not None:
        return _to_bool(config_value)

    env_value = _first_non_empty_from_env(
        ("MINI_APP_ENABLED", "mini_app_enabled", "MINIAPP_ENABLED")
    )
    if env_value is not None:
        return _to_bool(env_value)

    db_value = _safe_get_setting("mini_app_enabled", None)
    if db_value is not None:
        return _to_bool(db_value)

    return False


def get_mini_app_bind_host() -> str:
    config_value = _first_non_empty_from_config(
        ("MINI_APP_BIND_HOST", "mini_app_bind_host", "MINIAPP_BIND_HOST")
    )
    if config_value is not None:
        return str(config_value).strip()

    env_value = _first_non_empty_from_env(
        ("MINI_APP_BIND_HOST", "mini_app_bind_host", "MINIAPP_BIND_HOST")
    )
    if env_value is not None:
        return env_value

    db_value = _safe_get_setting("mini_app_bind_host", None)
    if db_value:
        return str(db_value).strip()

    return "0.0.0.0"


def get_mini_app_bind_port() -> int:
    raw = _first_non_empty_from_config(
        ("MINI_APP_BIND_PORT", "mini_app_bind_port", "MINIAPP_BIND_PORT")
    )
    if raw is None:
        raw = _first_non_empty_from_env(
            ("MINI_APP_BIND_PORT", "mini_app_bind_port", "MINIAPP_BIND_PORT")
        )
    if raw is None:
        raw = _safe_get_setting("mini_app_bind_port", None)
    if raw is None:
        raw = 8082

    try:
        return int(raw)
    except Exception:
        return 8082


def get_mini_app_public_url() -> str:
    config_value = _first_non_empty_from_config(
        ("MINI_APP_PUBLIC_URL", "mini_app_public_url", "MINIAPP_PUBLIC_URL")
    )
    if config_value is not None:
        return str(config_value).strip().rstrip("/")

    env_value = _first_non_empty_from_env(
        ("MINI_APP_PUBLIC_URL", "mini_app_public_url", "MINIAPP_PUBLIC_URL")
    )
    if env_value is not None:
        return env_value.rstrip("/")

    db_value = _safe_get_setting("mini_app_public_url", None)
    return str(db_value or "").strip().rstrip("/")


def get_mini_app_session_ttl_seconds() -> int:
    raw = _first_non_empty_from_config(
        (
            "MINI_APP_SESSION_TTL_SECONDS",
            "mini_app_session_ttl_seconds",
            "MINIAPP_SESSION_TTL_SECONDS",
        )
    )
    if raw is None:
        raw = _first_non_empty_from_env(
            (
                "MINI_APP_SESSION_TTL_SECONDS",
                "mini_app_session_ttl_seconds",
                "MINIAPP_SESSION_TTL_SECONDS",
            )
        )
    if raw is None:
        raw = _safe_get_setting("mini_app_session_ttl_seconds", None)
    if raw is None:
        raw = 12 * 60 * 60

    try:
        ttl = int(raw)
    except Exception:
        return 12 * 60 * 60

    if ttl < 60:
        return 60
    if ttl > 7 * 24 * 60 * 60:
        return 7 * 24 * 60 * 60
    return ttl
