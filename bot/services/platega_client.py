import logging
import os
import secrets
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Union

import aiohttp

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logger = logging.getLogger(__name__)

DEFAULT_PLATEGA_METHOD_IDS: Dict[str, int] = {
    "sbp": 2,
    # Per Platega integration docs:
    # card acquiring = 11, crypto payments = 13.
    "card": 11,
    "crypto": 13,
}

FALLBACK_METHOD_IDS: Dict[str, list[int]] = {
    # Some merchants still use legacy mapping.
    "sbp": [2],
    "card": [11, 10, 14, 15],
    "crypto": [13, 12],
}

PLATEGA_METHODS: Dict[str, Dict[str, Any]] = {
    "sbp": {
        "label": "СБП / QR",
        "api_aliases": ["SBPQR", "sbpqr", "SBP", "sbp", "qr"],
    },
    "card": {
        "label": "Карта РФ",
        "api_aliases": [
            "Card",
            "CARD",
            "CardRu",
            "CARDRU",
            "card",
            "CARD",
            "card_ru",
            "CARD_RU",
            "cards",
            "CARDS",
            "bank_card",
            "bankCard",
            "bankcard",
            "BANKCARD",
            "bank_cards",
            "BANK_CARDS",
            "RussianCard",
            "RUSSIAN_CARD",
        ],
    },
    "crypto": {
        "label": "Криптовалюта",
        "api_aliases": ["International", "INTERNATIONAL", "crypto", "CRYPTO", "intl", "INTL"],
    },
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
        return DEFAULT_PLATEGA_METHOD_IDS["sbp"]


def _intl_balance() -> str:
    db_raw = _db_get_setting("platega_intl_balance", None)
    if db_raw is not None and str(db_raw).strip():
        return str(db_raw).strip()
    return os.getenv("PLATEGA_INTL_BALANCE", "EUR").strip() or "EUR"


def _method_id_setting_key(code: str) -> str:
    return f"platega_method_{code}_id"


def _method_id_env_key(code: str) -> str:
    return f"PLATEGA_METHOD_{code.upper()}_ID"


def _method_id_for_code(code: str) -> Optional[int]:
    normalized = (code or "").strip().lower()
    if normalized not in PLATEGA_METHODS:
        return None

    db_raw = _db_get_setting(_method_id_setting_key(normalized), None)
    env_raw = os.getenv(_method_id_env_key(normalized), "").strip()
    raw = str(db_raw).strip() if db_raw is not None and str(db_raw).strip() else env_raw

    if not raw:
        return int(DEFAULT_PLATEGA_METHOD_IDS[normalized])

    try:
        return int(raw)
    except Exception:
        logger.warning("Invalid Platega method id for %s: %r", normalized, raw)
        return int(DEFAULT_PLATEGA_METHOD_IDS[normalized])


def _extra_fallback_ids_for_code(code: str) -> list[int]:
    normalized = (code or "").strip().lower()
    if normalized not in PLATEGA_METHODS:
        return []

    raw = _db_get_setting(f"platega_method_{normalized}_fallback_ids", None)
    if raw is None or not str(raw).strip():
        raw = os.getenv(f"PLATEGA_METHOD_{normalized.upper()}_FALLBACK_IDS", "")

    if not raw:
        return []

    out: list[int] = []
    for chunk in str(raw).replace(";", ",").split(","):
        val = str(chunk).strip()
        if not val:
            continue
        try:
            out.append(int(val))
        except Exception:
            logger.warning("Invalid Platega fallback id for %s: %r", normalized, val)
    return out


def _extra_aliases_for_code(code: str) -> list[str]:
    normalized = (code or "").strip().lower()
    if normalized not in PLATEGA_METHODS:
        return []

    raw = _db_get_setting(f"platega_method_{normalized}_aliases", None)
    if raw is None or not str(raw).strip():
        raw = os.getenv(f"PLATEGA_METHOD_{normalized.upper()}_ALIASES", "")

    if not raw:
        return []

    out: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        alias = str(chunk).strip()
        if alias:
            out.append(alias)
    return out


def get_platega_payment_method_id(code: str) -> Optional[int]:
    return _method_id_for_code(code)


def get_enabled_platega_methods() -> list[tuple[str, str, int]]:
    methods = [
        ("sbp", "СБП", "platega_method_sbp_enabled"),
        ("card", "Карта РФ", "platega_method_card_enabled"),
        ("crypto", "Криптовалюта", "platega_method_crypto_enabled"),
    ]
    enabled: list[tuple[str, str, int]] = []

    for code, label, setting_key in methods:
        if not _to_bool(_db_get_setting(setting_key, "1"), default=True):
            continue
        method_id = _method_id_for_code(code)
        if method_id is None:
            continue
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
        for key in PLATEGA_METHODS.keys():
            method_id = _method_id_for_code(key)
            if method_id == value:
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
        "qr": "sbp",
        "cardru": "card",
        "international": "crypto",
        "intl": "crypto",
    }
    if lowered in aliases:
        return aliases[lowered]

    try:
        numeric = int(raw)
    except Exception:
        numeric = None

    if numeric is not None:
        for key in PLATEGA_METHODS.keys():
            method_id = _method_id_for_code(key)
            if method_id == numeric:
                return key

    return None


def _dedupe_values(seq: list[Union[int, str, None]]) -> list[Union[int, str, None]]:
    out: list[Union[int, str, None]] = []
    seen: set[str] = set()

    for item in seq:
        marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)

    return out


def _method_candidates_for_key(method_key: str) -> list[Union[int, str, None]]:
    method_id = _method_id_for_code(method_key)
    aliases = list(PLATEGA_METHODS[method_key].get("api_aliases", []))
    aliases.extend(_extra_aliases_for_code(method_key))
    candidates: list[Union[int, str, None]] = []

    candidate_ids: list[int] = []
    if method_id is not None:
        candidate_ids.append(method_id)
    for fallback_id in FALLBACK_METHOD_IDS.get(method_key, []):
        if fallback_id not in candidate_ids:
            candidate_ids.append(fallback_id)
    for fallback_id in _extra_fallback_ids_for_code(method_key):
        if fallback_id not in candidate_ids:
            candidate_ids.append(fallback_id)

    for cid in candidate_ids:
        candidates.extend([cid, str(cid)])

    candidates.extend(aliases)
    return _dedupe_values(candidates)


def _payment_method_candidates(value: Optional[Union[int, str]]) -> list[Union[int, str, None]]:
    method_key = _method_key_from_value(value)
    if method_key:
        # IMPORTANT:
        # If user explicitly selected a payment method, do not silently fallback
        # to another method (e.g., SBP), otherwise card/crypto choice is lost.
        return _method_candidates_for_key(method_key)

    if value is None:
        default_key = _method_key_from_value(_payment_method())
        if default_key:
            return _method_candidates_for_key(default_key)
        return [None]

    return [value]


def _normalize_amount_rub(value: Union[int, float, str, Decimal]) -> Decimal:
    try:
        amount = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValueError("amount_rub must be a valid number")

    if amount <= 0:
        raise ValueError("amount_rub must be positive")

    return amount.quantize(Decimal("0.01"))


def _build_payload(
    *,
    amount_rub: Decimal,
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
            "amount": f"{amount_rub:.2f}",
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
    method_code_hint: Optional[str] = None,
) -> Dict[str, Any]:
    amount_rub_normalized = _normalize_amount_rub(amount_rub)

    url = f"{_base_url()}/transaction/process"
    resolved_method: Optional[Union[int, str]] = payment_method if payment_method is not None else _payment_method()

    hint_key = (method_code_hint or "").strip().lower()
    if hint_key in PLATEGA_METHODS:
        method_candidates = _method_candidates_for_key(hint_key)
    else:
        method_candidates = _payment_method_candidates(resolved_method)

    base_headers = _headers()

    data: Optional[Dict[str, Any]] = None
    final_payload: Optional[Dict[str, Any]] = None
    final_error: Optional[str] = None

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for method_candidate in method_candidates:
            request_id = secrets.token_hex(8)
            headers = dict(base_headers)
            headers["X-Request-Id"] = request_id
            payload = _build_payload(
                amount_rub=amount_rub_normalized,
                order_id=order_id,
                description=description,
                success_url=success_url,
                fail_url=fail_url,
                payment_method=method_candidate,
            )
            payload_variants: list[Dict[str, Any]] = [payload]
            # Some Platega deployments validate payload through wrapper object "command".
            payload_variants.append({"command": payload})

            candidate_done = False
            for payload_variant in payload_variants:
                final_payload = payload_variant
                try:
                    async with session.post(url, json=payload_variant, headers=headers) as response:
                        text = await response.text()
                        status = response.status
                except aiohttp.ClientError as exc:
                    logger.error(
                        "Platega create-payment network error: request_id=%s payload=%s error=%s",
                        request_id,
                        payload_variant,
                        exc,
                    )
                    final_error = f"network error: {exc}"
                    continue

                if status >= 400:
                    logger.error(
                        "Platega create-payment error: status=%s request_id=%s payload=%s response=%s",
                        status,
                        request_id,
                        payload_variant,
                        text,
                    )
                    final_error = f"HTTP {status}"
                    continue

                try:
                    data = json.loads(text)
                except Exception:
                    logger.error("Platega create-payment invalid JSON: status=%s body=%s", status, text)
                    final_error = "invalid JSON response"
                    continue

                if isinstance(data, dict) and data.get("ok") is False:
                    final_error = str(data.get("message") or data.get("detail") or "provider rejected request")
                    logger.error(
                        "Platega create-payment provider rejection: request_id=%s payload=%s response=%s",
                        request_id,
                        payload_variant,
                        data,
                    )
                    continue

                candidate_done = True
                break

            if candidate_done:
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

