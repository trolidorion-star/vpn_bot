import logging
import os
import secrets
from typing import Any, Dict, Optional, Union

import aiohttp

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logger = logging.getLogger(__name__)

PLATEGA_METHOD_SBP = 2
PLATEGA_METHOD_CARD_RU = 10
PLATEGA_METHOD_INTL = 12

PLATEGA_METHODS: Dict[str, Dict[str, Any]] = {
    "sbp": {"id": PLATEGA_METHOD_SBP, "label": "СБП / QR", "api": [PLATEGA_METHOD_SBP, "SBPQR"]},
    "card": {"id": PLATEGA_METHOD_CARD_RU, "label": "Карта РФ", "api": [PLATEGA_METHOD_CARD_RU, "CardRu"]},
    "crypto": {"id": PLATEGA_METHOD_INTL, "label": "Криптовалюта", "api": [PLATEGA_METHOD_INTL, "International"]},
}


def _db_get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        from database.requests import get_setting

        return get_setting(key, default)
    except Exception:
        return default


def _to_bool(raw: Optional[str], default: bool = False) -> bool:
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def _enabled() -> bool:
    db_raw = _db_get_setting("platega_enabled", None)
    if db_raw is not None:
        return _to_bool(db_raw, default=True)
    return _to_bool(os.getenv("PLATEGA_ENABLED", "1"), default=True)


def is_platega_test_mode() -> bool:
    db_raw = _db_get_setting("platega_test_mode", None)
    if db_raw is not None:
        return _to_bool(db_raw, default=False)
    return _to_bool(os.getenv("PLATEGA_TEST_MODE", "0"), default=False)


def _base_url() -> str:
    return (os.getenv("PLATEGA_BASE_URL", "https://app.platega.io").strip() or "https://app.platega.io").rstrip("/")


def _merchant_id() -> str:
    return os.getenv("PLATEGA_MERCHANT_ID", "").strip()


def _api_key() -> str:
    return os.getenv("PLATEGA_API_KEY", "").strip()


def _payment_method() -> int:
    db_raw = _db_get_setting("platega_payment_method", None)
    if db_raw is not None and str(db_raw).strip():
        raw = str(db_raw).strip()
    else:
        raw = os.getenv("PLATEGA_PAYMENT_METHOD", "2").strip()
    try:
        return int(raw)
    except Exception:
        return 2


def _intl_balance() -> str:
    db_raw = _db_get_setting("platega_intl_balance", None)
    if db_raw is not None and str(db_raw).strip():
        return str(db_raw).strip()
    return os.getenv("PLATEGA_INTL_BALANCE", "EUR").strip() or "EUR"


def get_platega_payment_method_id(code: str) -> Optional[int]:
    method = PLATEGA_METHODS.get((code or "").strip().lower())
    if not method:
        return None
    return int(method["id"])


def get_enabled_platega_methods() -> list[tuple[str, str, int]]:
    methods = [
        ("sbp", "СБП", PLATEGA_METHOD_SBP, "platega_method_sbp_enabled"),
        ("card", "Карта РФ", PLATEGA_METHOD_CARD_RU, "platega_method_card_enabled"),
        ("crypto", "Криптовалюта", PLATEGA_METHOD_INTL, "platega_method_crypto_enabled"),
    ]
    enabled: list[tuple[str, str, int]] = []
    for code, label, method_id, setting_key in methods:
        if _to_bool(_db_get_setting(setting_key, "1"), default=True):
            enabled.append((code, label, method_id))
    return enabled


def is_platega_method_enabled(code: str) -> bool:
    for method_code, _label, _method_id in get_enabled_platega_methods():
        if method_code == code:
            return True
    return False


def is_platega_ready() -> bool:
    return _enabled() and bool(_merchant_id() and _api_key())


def _headers() -> Dict[str, str]:
    merchant_id = _merchant_id()
    api_key = _api_key()
    if not merchant_id or not api_key:
        raise ValueError("Platega credentials are not configured: PLATEGA_MERCHANT_ID / PLATEGA_API_KEY")
    return {
        "X-MerchantId": merchant_id,
        "X-Secret": api_key,
        "Content-Type": "application/json",
    }


def _method_key_from_value(value: Optional[Union[int, str]]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, int):
        for key, meta in PLATEGA_METHODS.items():
            if int(meta["id"]) == value:
                return key
        return None

    raw = str(value).strip()
    if not raw:
        return None
    lowered = raw.lower()
    if lowered in PLATEGA_METHODS:
        return lowered

    aliases = {
        "sbpqr": "sbp",
        "cardru": "card",
        "international": "crypto",
    }
    if lowered in aliases:
        return aliases[lowered]

    try:
        numeric = int(raw)
    except Exception:
        numeric = None
    if numeric is not None:
        for key, meta in PLATEGA_METHODS.items():
            if int(meta["id"]) == numeric:
                return key
    return None


def _payment_method_candidates(value: Optional[Union[int, str]]) -> list[Union[int, str, None]]:
    method_key = _method_key_from_value(value)
    if method_key:
        return list(PLATEGA_METHODS[method_key]["api"])
    if value is None:
        return [None]
    return [value]


def _build_payload(
    *,
    amount_rub: int,
    order_id: str,
    description: str,
    success_url: str,
    fail_url: str,
    payment_method: Optional[Union[int, str]],
) -> Dict[str, Any]:
    payload = {
        "description": description,
        "externalId": order_id,
        "payload": order_id,
        "paymentDetails": {
            "amount": int(amount_rub),
            "currency": "RUB",
        },
        "return": success_url,
        "failedUrl": fail_url,
    }
    if payment_method is not None:
        payload["paymentMethod"] = payment_method

    method_key = _method_key_from_value(payment_method)
    if method_key == "crypto":
        payload["balance"] = _intl_balance()
    return payload


async def create_payment_link(
    *,
    amount_rub: int,
    order_id: str,
    description: str,
    success_url: str,
    fail_url: str,
    payment_method: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    if amount_rub <= 0:
        raise ValueError("amount_rub must be positive")
    amount_rub = int(amount_rub)

    url = f"{_base_url()}/transaction/process"
    resolved_method: Optional[Union[int, str]] = payment_method if payment_method is not None else _payment_method()
    method_candidates = _payment_method_candidates(resolved_method)

    request_id = secrets.token_hex(8)
    headers = _headers()
    headers["X-Request-Id"] = request_id

    data: Optional[Dict[str, Any]] = None
    final_payload: Optional[Dict[str, Any]] = None
    final_error: Optional[str] = None

    async with aiohttp.ClientSession() as session:
        for method_candidate in method_candidates:
            payload = _build_payload(
                amount_rub=amount_rub,
                order_id=order_id,
                description=description,
                success_url=success_url,
                fail_url=fail_url,
                payment_method=method_candidate,
            )
            final_payload = payload
            async with session.post(url, json=payload, headers=headers) as response:
                text = await response.text()
                if response.status >= 400:
                    logger.error(
                        "Platega create-payment error: status=%s request_id=%s payload=%s response=%s",
                        response.status,
                        request_id,
                        payload,
                        text,
                    )
                    final_error = f"HTTP {response.status}"
                    continue

                try:
                    data = await response.json()
                except Exception:
                    logger.error("Platega create-payment invalid JSON: status=%s body=%s", response.status, text)
                    final_error = "invalid JSON response"
                    continue
                break

    if data is None:
        details = f" (last payload={final_payload})" if final_payload else ""
        raise RuntimeError(f"Platega create payment failed: {final_error or 'unknown error'}{details}")

    transaction_id = str(data.get("id") or data.get("transactionId") or "").strip()
    redirect_url = (
        data.get("redirect")
        or data.get("payformUrl")
        or data.get("payform")
        or data.get("paymentUrl")
        or data.get("url")
        or data.get("redirectUrl")
    )
    if not transaction_id or not redirect_url:
        logger.error("Platega create-payment missing fields: response=%s", data)
        raise RuntimeError("Platega create payment response is missing transaction id or redirect url")

    return {
        "transaction_id": transaction_id,
        "redirect_url": str(redirect_url),
        "raw": data,
    }


async def get_transaction_status(transaction_id: str) -> Dict[str, Any]:
    if not transaction_id:
        raise ValueError("transaction_id is required")

    url = f"{_base_url()}/transaction/{transaction_id}"
    headers = _headers()
    request_id = secrets.token_hex(8)
    headers["X-Request-Id"] = request_id

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            text = await response.text()
            if response.status >= 400:
                logger.error(
                    "Platega status-check error: status=%s transaction_id=%s request_id=%s response=%s",
                    response.status,
                    transaction_id,
                    request_id,
                    text,
                )
                raise RuntimeError(f"Platega status check failed with HTTP {response.status}")

            try:
                data = await response.json()
            except Exception:
                logger.error("Platega status-check invalid JSON: status=%s body=%s", response.status, text)
                raise RuntimeError("Platega status check returned invalid JSON")

    return data
