"""
Утилиты для работы с URL Mini App.
"""
from __future__ import annotations

from urllib.parse import urlparse
import config as app_config
from database.requests import get_setting


def sanitize_mini_app_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if "your_mini_app_url" in lowered:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    if not parsed.netloc:
        return ""
    return value


def resolve_mini_app_url() -> str:
    """
    Возвращает валидный URL Mini App.
    Приоритет:
    1) ENV MINI_APP_URL
    2) settings.mini_app_url
    3) settings.web_app_url
    4) settings.miniapp_url
    """
    env_url = sanitize_mini_app_url((getattr(app_config, "MINI_APP_URL", "") or "").strip())
    if env_url:
        return env_url

    for key in ("mini_app_url", "web_app_url", "miniapp_url"):
        value = sanitize_mini_app_url((get_setting(key, "") or "").strip())
        if value:
            return value
    return ""

