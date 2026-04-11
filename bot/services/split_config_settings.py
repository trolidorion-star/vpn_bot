from database.requests import get_setting

import config as app_config


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    s = str(value or "").strip().lower()
    return s in {"1", "true", "yes", "on"}


def get_split_config_enabled() -> bool:
    # Приоритет: config.py -> БД fallback
    if hasattr(app_config, "SPLIT_CONFIG_ENABLED"):
        return _to_bool(getattr(app_config, "SPLIT_CONFIG_ENABLED"))
    db_value = get_setting("split_config_enabled", None)
    return _to_bool(db_value)


def get_split_config_bind_host() -> str:
    # Приоритет: config.py -> БД fallback
    if hasattr(app_config, "SPLIT_CONFIG_BIND_HOST"):
        v = str(getattr(app_config, "SPLIT_CONFIG_BIND_HOST") or "").strip()
        if v:
            return v
    db_value = get_setting("split_config_bind_host", None)
    if db_value:
        return str(db_value).strip()
    return "0.0.0.0"


def get_split_config_bind_port() -> int:
    # Приоритет: config.py -> БД fallback
    if hasattr(app_config, "SPLIT_CONFIG_BIND_PORT"):
        raw = getattr(app_config, "SPLIT_CONFIG_BIND_PORT")
    else:
        raw = get_setting("split_config_bind_port", None)
    if raw is None:
        raw = 8081
    try:
        return int(raw)
    except Exception:
        return 8081


def get_split_config_public_base_url() -> str:
    # Приоритет: config.py -> БД fallback
    if hasattr(app_config, "SPLIT_CONFIG_PUBLIC_BASE_URL"):
        cfg = str(getattr(app_config, "SPLIT_CONFIG_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if cfg:
            return cfg
    db_value = get_setting("split_config_public_base_url", None)
    return str(db_value or "").strip().rstrip("/")
