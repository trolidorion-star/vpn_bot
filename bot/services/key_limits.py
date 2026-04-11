from database.requests import get_setting


def get_key_connection_limit() -> int:
    """
    Возвращает лимит одновременных устройств для одного ключа.
    По умолчанию: 2.
    """
    raw = get_setting("key_connection_limit", "2")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 2
    return min(10, max(1, value))
