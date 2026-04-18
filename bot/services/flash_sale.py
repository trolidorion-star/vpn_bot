import datetime
from typing import Any, Dict, List

from database.requests import create_or_update_promocode, get_setting, set_setting


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_iso_utc(value: str) -> datetime.datetime | None:
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(datetime.timezone.utc)
    except Exception:
        return None


def _to_int(raw: str, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return default


def get_flash_sale_state() -> Dict[str, Any]:
    """
    Возвращает текущее состояние акции с таймером.
    Если таймер истёк:
    - при auto_restart=1 стартует новый цикл;
    - иначе акция выключается.
    """
    enabled = get_setting("flash_sale_enabled", "0") == "1"
    sale_price_rub = _to_int(get_setting("flash_sale_price_rub", "249"), 249)
    base_price_rub = _to_int(get_setting("flash_sale_base_price_rub", "300"), 300)
    duration_hours = max(1, _to_int(get_setting("flash_sale_duration_hours", "24"), 24))
    auto_restart = get_setting("flash_sale_auto_restart", "0") == "1"
    promo_code = get_setting("flash_sale_promo_code", "FLASH24")

    started_raw = get_setting("flash_sale_started_at", "")
    started_at = _parse_iso_utc(started_raw)
    now = _utc_now()

    if enabled and started_at is None:
        started_at = now
        set_setting("flash_sale_started_at", started_at.isoformat())

    remaining_seconds = 0
    end_at = None
    active = False

    if enabled and started_at is not None:
        end_at = started_at + datetime.timedelta(hours=duration_hours)
        if now >= end_at:
            if auto_restart:
                while now >= end_at:
                    started_at = end_at
                    end_at = started_at + datetime.timedelta(hours=duration_hours)
                set_setting("flash_sale_started_at", started_at.isoformat())
                active = True
            else:
                set_setting("flash_sale_enabled", "0")
                enabled = False
                active = False
        else:
            active = True

        if active and end_at is not None:
            remaining_seconds = max(0, int((end_at - now).total_seconds()))

    state = {
        "enabled": enabled,
        "active": active,
        "sale_price_rub": max(1, sale_price_rub),
        "base_price_rub": max(1, base_price_rub),
        "duration_hours": duration_hours,
        "auto_restart": auto_restart,
        "promo_code": promo_code,
        "started_at": started_at,
        "end_at": end_at,
        "remaining_seconds": remaining_seconds,
    }

    code = str(state.get("promo_code") or "").strip().upper()
    base_price = int(state.get("base_price_rub") or 0)
    sale_price = int(state.get("sale_price_rub") or 0)
    if code:
        discount_percent = 0
        if base_price > 0 and sale_price > 0 and sale_price < base_price:
            discount_percent = round(((base_price - sale_price) / base_price) * 100)
        discount_percent = max(1, min(95, int(discount_percent or 0)))
        try:
            create_or_update_promocode(
                code=code,
                discount_type="PERCENT",
                discount_value=discount_percent,
                min_amount=1,
                is_active=bool(state.get("enabled")),
                visibility="PUBLIC",
            )
        except Exception:
            pass

    return state


def format_remaining_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def apply_flash_sale_to_tariff(tariff: Dict[str, Any]) -> Dict[str, Any]:
    """
    Применяет акционную цену к тарифу в RUB, если акция активна.
    Применяется только к тарифам, у которых price_rub == flash_sale_base_price_rub.
    """
    if not tariff:
        return tariff

    result = dict(tariff)
    state = get_flash_sale_state()
    result["flash_sale_active"] = False

    if not state["active"]:
        return result

    current_rub = int(result.get("price_rub") or 0)
    if current_rub != state["base_price_rub"]:
        return result

    result["original_price_rub"] = current_rub
    result["price_rub"] = state["sale_price_rub"]
    result["flash_sale_active"] = True
    result["flash_sale_remaining_seconds"] = state["remaining_seconds"]
    result["flash_sale_promo_code"] = state["promo_code"]
    return result


def apply_flash_sale_to_tariffs(tariffs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [apply_flash_sale_to_tariff(t) for t in tariffs]

