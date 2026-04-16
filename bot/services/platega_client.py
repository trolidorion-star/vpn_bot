import logging
import os
import secrets
from typing import Any, Dict, Optional

import aiohttp

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    raw = os.getenv("PLATEGA_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on", "y"}


def _base_url() -> str:
    return (os.getenv("PLATEGA_BASE_URL", "https://app.platega.io").strip() or "https://app.platega.io").rstrip("/")


def _merchant_id() -> str:
    return os.getenv("PLATEGA_MERCHANT_ID", "").strip()


def _api_key() -> str:
    return os.getenv("PLATEGA_API_KEY", "").strip()


def _payment_method() -> int:
    raw = os.getenv("PLATEGA_PAYMENT_METHOD", "2").strip()
    try:
        return int(raw)
    except Exception:
        return 2


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


async def create_payment_link(
    *,
    amount_rub: int,
    order_id: str,
    description: str,
    success_url: str,
    fail_url: str,
    payment_method: Optional[int] = None,
) -> Dict[str, Any]:
    if amount_rub <= 0:
        raise ValueError("amount_rub must be positive")

    url = f"{_base_url()}/transaction/process"
    payload = {
        "amount": amount_rub,
        "currency": "RUB",
        "description": description,
        "externalId": order_id,
        "payload": order_id,
        "paymentMethod": int(payment_method or _payment_method()),
        "returnUrl": success_url,
        "failedUrl": fail_url,
    }
    request_id = secrets.token_hex(8)
    headers = _headers()
    headers["X-Request-Id"] = request_id

    async with aiohttp.ClientSession() as session:
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
                raise RuntimeError(f"Platega create payment failed with HTTP {response.status}")

            try:
                data = await response.json()
            except Exception:
                logger.error("Platega create-payment invalid JSON: status=%s body=%s", response.status, text)
                raise RuntimeError("Platega create payment returned invalid JSON")

    transaction_id = str(data.get("id") or "").strip()
    redirect_url = (
        data.get("payformUrl")
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
