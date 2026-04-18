import hmac
import json
import logging
import os
from typing import Optional

from aiohttp import web

from bot.services.billing import process_payment_order, process_referral_reward
from bot.services.platega_client import get_transaction_status
from bot.services.vpn_api import push_key_to_panel, restore_traffic_limit_in_db
from database.requests import (
    create_or_update_transaction,
    find_order_by_order_id,
    find_transaction_by_order_id,
    find_transaction_by_payment_id,
    get_user_by_id,
    is_order_already_paid,
    consume_order_promocode,
    update_transaction_status,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None
_bot = None


def _normalize_amount(value) -> int:
    """
    Tries to normalize provider amount into integer rubles.
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(float(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        for suffix in ("RUB", "rub", "₽"):
            cleaned = cleaned.replace(suffix, "")
        cleaned = cleaned.strip()
        try:
            return int(float(cleaned))
        except Exception:
            return 0
    return 0


def _enabled() -> bool:
    raw = os.getenv("PLATEGA_WEBHOOK_ENABLED", "1").strip().lower()
    return raw in {"1", "true", "yes", "on", "y"}


def _host() -> str:
    return os.getenv("PLATEGA_WEBHOOK_HOST", "0.0.0.0").strip() or "0.0.0.0"


def _port() -> int:
    raw = os.getenv("PLATEGA_WEBHOOK_PORT", "8082").strip()
    try:
        return int(raw)
    except Exception:
        return 8082


def _merchant_id() -> str:
    return os.getenv("PLATEGA_MERCHANT_ID", "").strip()


def _api_key() -> str:
    return os.getenv("PLATEGA_API_KEY", "").strip()


def _webhook_token() -> str:
    return os.getenv("PLATEGA_WEBHOOK_TOKEN", "").strip()


def _get_header(request: web.Request, *names: str) -> str:
    for name in names:
        value = (request.headers.get(name) or "").strip()
        if value:
            return value
    return ""


def _verify_headers(request: web.Request) -> bool:
    # Prefer explicit webhook token when configured.
    expected_token = _webhook_token()
    if expected_token:
        got_token = (
            _get_header(request, "X-Webhook-Token", "X-WebhookToken", "Webhook-Token", "X-Token")
            or (request.query.get("token") or "").strip()
        )
        if got_token and hmac.compare_digest(got_token, expected_token):
            return True

    expected_merchant = _merchant_id()
    expected_secret = _api_key()
    if expected_merchant and expected_secret:
        # Support common header variants from provider/proxies.
        got_merchant = _get_header(request, "X-MerchantId", "X-Merchant-ID", "MerchantId", "merchantId")
        got_secret = _get_header(request, "X-Secret", "X-Api-Key", "X-ApiKey", "Api-Key")
        return hmac.compare_digest(got_merchant, expected_merchant) and hmac.compare_digest(got_secret, expected_secret)

    # If only token is configured, we already validated above (if present).
    return False


async def _notify_user(order: dict, text: str) -> None:
    if _bot is None:
        return
    user = get_user_by_id(order["user_id"])
    telegram_id = user.get("telegram_id") if user else None
    if not telegram_id:
        return
    try:
        await _bot.send_message(telegram_id, text)
    except Exception as e:
        logger.warning("Unable to notify user %s for order %s: %s", telegram_id, order.get("order_id"), e)


async def _sync_key_limit(order: dict) -> None:
    key_id = int(order.get("vpn_key_id") or 0)
    if key_id <= 0:
        return
    try:
        restore_traffic_limit_in_db(key_id)
        await push_key_to_panel(key_id, reset_traffic=True)
    except Exception as e:
        logger.error("Failed to sync key %s to panel after payment: %s", key_id, e)


async def _resolve_transaction(order_tx: Optional[dict], transaction_id: str) -> Optional[dict]:
    if order_tx:
        return order_tx

    tx = find_transaction_by_payment_id(transaction_id)
    if tx:
        return tx

    try:
        status_payload = await get_transaction_status(transaction_id)
    except Exception as e:
        logger.warning("Platega fallback status query failed for %s: %s", transaction_id, e)
        return None

    order_id = str(status_payload.get("payload") or status_payload.get("externalId") or "").strip()
    if not order_id:
        return None

    tx = find_transaction_by_order_id(order_id)
    if tx:
        update_transaction_status(order_id=order_id, status=tx["status"], payment_id=transaction_id, payload=status_payload)
        return find_transaction_by_order_id(order_id)

    order = find_order_by_order_id(order_id)
    if not order:
        return None

    payment_details = status_payload.get("paymentDetails") or {}
    amount = _normalize_amount(payment_details.get("amount") or status_payload.get("amount") or 0)
    currency = payment_details.get("currency") or status_payload.get("currency") or "RUB"
    create_or_update_transaction(
        order_id=order_id,
        user_id=order["user_id"],
        amount=amount,
        currency=str(currency or "RUB"),
        payment_id=transaction_id,
        status="PENDING",
        payload=status_payload,
    )
    return find_transaction_by_order_id(order_id)


def _parse_tx_payload(tx: Optional[dict]) -> dict:
    if not tx:
        return {}
    raw = tx.get("payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return {}


async def _platega_webhook_handler(request: web.Request) -> web.Response:
    if not _verify_headers(request):
        logger.warning(
            "Platega webhook auth failed: has_token=%s has_merchant=%s has_secret=%s",
            bool(_get_header(request, "X-Webhook-Token", "X-WebhookToken", "Webhook-Token", "X-Token") or (request.query.get("token") or "").strip()),
            bool(_get_header(request, "X-MerchantId", "X-Merchant-ID", "MerchantId", "merchantId")),
            bool(_get_header(request, "X-Secret", "X-Api-Key", "X-ApiKey", "Api-Key")),
        )
        return web.Response(status=403, text="Forbidden")

    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="Invalid JSON")

    transaction_id = str(payload.get("id") or payload.get("transactionId") or "").strip()
    status = str(payload.get("status") or "").strip().upper()
    if not transaction_id:
        return web.Response(status=400, text="Missing id")

    tx = await _resolve_transaction(None, transaction_id)
    if not tx:
        logger.warning("Platega webhook transaction not found: id=%s payload=%s", transaction_id, payload)
        return web.Response(status=404, text="Transaction not found")

    order_id = tx["order_id"]
    order = find_order_by_order_id(order_id)
    tx_payload = _parse_tx_payload(tx)

    if not order:
        # Admin test payments are intentionally not linked to subscription orders.
        if tx_payload.get("kind") == "admin_test_platega":
            if status == "CONFIRMED":
                update_transaction_status(order_id=order_id, status="SUCCESS", payment_id=transaction_id, payload=payload)
                await _notify_user({"user_id": tx["user_id"]}, "✅ Тестовый платеж Platega подтвержден.")
                return web.Response(status=200, text="OK")
            if status in {"CANCELED", "CHARGEBACK", "CHARGEBACKED"}:
                update_transaction_status(order_id=order_id, status="FAILED", payment_id=transaction_id, payload=payload)
                return web.Response(status=200, text="OK")
            update_transaction_status(order_id=order_id, status="PENDING", payment_id=transaction_id, payload=payload)
            return web.Response(status=200, text="OK")

        logger.warning("Platega webhook order not found: order_id=%s transaction_id=%s", order_id, transaction_id)
        return web.Response(status=404, text="Order not found")


    if status in {"CONFIRMED", "SUCCESS", "PAID"}:
        if tx.get("status") == "SUCCESS" or is_order_already_paid(order_id):
            update_transaction_status(order_id=order_id, status="SUCCESS", payment_id=transaction_id, payload=payload)
            return web.Response(status=200, text="OK")

        success, text, updated_order = await process_payment_order(order_id)
        if not success:
            logger.error("Platega webhook process order failed: order_id=%s message=%s", order_id, text)
            return web.Response(status=500, text="Order processing failed")

        update_transaction_status(order_id=order_id, status="SUCCESS", payment_id=transaction_id, payload=payload)
        if not consume_order_promocode(order_id):
            logger.warning("Promo consume failed for order_id=%s", order_id)
        final_order = updated_order or order
        await _sync_key_limit(final_order)
        days = final_order.get("period_days") or final_order.get("duration_days") or 30
        amount_kopecks = int(tx.get("amount") or 0) * 100
        payment_method = str((tx_payload.get("method") or "card")).strip().lower()
        reward_type = "crypto" if payment_method == "crypto" else "cards"
        await process_referral_reward(final_order["user_id"], days, amount_kopecks, reward_type)
        await _notify_user(final_order, "✅ Оплата прошла успешно. Подписка обновлена.")
        return web.Response(status=200, text="OK")

    if status in {"CANCELED", "CHARGEBACK", "CHARGEBACKED"}:
        if tx.get("status") != "SUCCESS":
            update_transaction_status(order_id=order_id, status="FAILED", payment_id=transaction_id, payload=payload)
        return web.Response(status=200, text="OK")

    update_transaction_status(order_id=order_id, status="PENDING", payment_id=transaction_id, payload=payload)
    return web.Response(status=200, text="OK")


async def _health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def start_platega_webhook_server(bot) -> None:
    global _runner, _site, _bot

    if _runner is not None:
        return

    if not _enabled():
        logger.info("Platega webhook server disabled by PLATEGA_WEBHOOK_ENABLED")
        return

    if not _webhook_token() and (not _merchant_id() or not _api_key()):
        logger.info("Platega webhook server disabled: missing auth config (PLATEGA_WEBHOOK_TOKEN or PLATEGA_MERCHANT_ID/PLATEGA_API_KEY)")
        return

    _bot = bot
    app = web.Application()
    app.add_routes(
        [
            web.post("/webhook/platega", _platega_webhook_handler),
            web.get("/webhook/platega/health", _health_handler),
        ]
    )

    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host=_host(), port=_port())
    try:
        await _site.start()
        logger.info("Platega webhook server started on %s:%s", _host(), _port())
    except Exception:
        await _runner.cleanup()
        _runner = None
        _site = None
        _bot = None
        raise


async def stop_platega_webhook_server() -> None:
    global _runner, _site, _bot
    if _site:
        try:
            await _site.stop()
        except Exception:
            pass
    if _runner:
        try:
            await _runner.cleanup()
        except Exception:
            pass
    _runner = None
    _site = None
    _bot = None
