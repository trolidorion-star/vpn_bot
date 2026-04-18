import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
import logging
import aiohttp
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import dotenv_values, load_dotenv

from bot.services.platega_client import (
    create_payment_link,
    get_platega_payment_method_id,
    is_platega_method_enabled,
    is_platega_ready,
)
from bot.services.flash_sale import get_flash_sale_state
from bot.services.ru_bypass import get_default_ru_exclusions
from bot.services.split_config_settings import get_split_config_public_base_url
from bot.services.vpn_api import get_client
from bot.utils.key_generator import generate_link
from config import ADMIN_IDS
from database.connection import get_db
from database.requests import (
    apply_promocode_to_order,
    add_key_exclusion_for_user,
    add_ticket_message,
    count_direct_paid_referrals,
    count_direct_referrals,
    clear_user_active_promocode,
    create_support_ticket,
    get_user_active_promocode,
    get_promocode,
    create_or_update_transaction,
    create_pending_order,
    ensure_user_referral_code,
    get_active_referral_levels,
    get_all_tariffs,
    get_direct_referrals_with_purchase_info,
    get_key_details_for_user,
    get_or_create_user,
    get_open_ticket_for_user,
    list_user_tickets,
    list_admin_tickets,
    get_ticket_by_id,
    get_ticket_messages,
    get_referral_reward_type,
    get_referral_stats,
    get_tariff_by_id,
    get_user_balance,
    get_user_keys_for_display,
    is_miniapp_enabled,
    is_referral_enabled,
    set_user_active_promocode,
    set_miniapp_enabled,
    update_key_custom_name,
    update_transaction_status,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "webapp" / "frontend"
load_dotenv(ROOT_DIR / ".env")
BOT_RETURN_URL = os.getenv("BOT_RETURN_URL", "https://t.me/BobrikVPNbot")
SESSION_TTL_SECONDS = int(os.getenv("MINI_APP_SESSION_TTL", "21600"))
TELEGRAM_INITDATA_TTL_SECONDS = max(86400, int(os.getenv("TELEGRAM_INITDATA_TTL", "86400")))
BOT_TOKEN_ENV_FILES = (
    ROOT_DIR / ".env",
    ROOT_DIR / "deploy" / ".env",
    Path("/etc/bobrik/.env"),
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bobrik Mini App API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def miniapp_gatekeeper(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and not is_miniapp_enabled():
        allowed_paths = {
            "/api/health",
            "/api/app_state",
            "/api/admin/miniapp_state",
        }
        if path not in allowed_paths:
            return JSONResponse(
                status_code=503,
                content={"ok": False, "detail": "Mini App is temporarily disabled for maintenance"},
            )
    return await call_next(request)

_sessions: dict[str, dict[str, Any]] = {}


class SessionRequest(BaseModel):
    initData: str


class InvoiceRequest(BaseModel):
    tariff_id: int
    method: str
    key_id: Optional[int] = None
    promo_code: Optional[str] = None
    use_promo: bool = True


class RuBypassRequest(BaseModel):
    key_id: int
    enabled: bool


class AdminMiniAppToggleRequest(BaseModel):
    enabled: bool


class SupportTicketRequest(BaseModel):
    message: str


class RenameKeyRequest(BaseModel):
    name: str


def _bot_token() -> str:
    token = _normalize_secret(os.getenv("BOT_TOKEN", ""))
    if token:
        return token

    for env_path in BOT_TOKEN_ENV_FILES:
        if not env_path.exists():
            continue
        try:
            values = dotenv_values(env_path)
        except Exception as exc:
            logger.warning("Failed to read BOT_TOKEN from %s: %s", env_path, exc)
            continue
        token = _normalize_secret(values.get("BOT_TOKEN", "") if isinstance(values, dict) else "")
        if token:
            return token

    raise RuntimeError("BOT_TOKEN is required")


def _normalize_secret(raw_value: Any) -> str:
    return re.sub(r"[\u200b-\u200d\u2060\ufeff]", "", str(raw_value or "")).strip().strip("'\"")


def _parse_admin_ids() -> set[int]:
    ids: set[int] = {int(value) for value in ADMIN_IDS if str(value).isdigit()}
    raw = " ".join(
        filter(
            None,
            [
                os.getenv("MINIAPP_ADMIN_IDS", ""),
                os.getenv("ADMIN_IDS", ""),
                os.getenv("BOT_ADMIN_IDS", ""),
            ],
        )
    )
    for part in re.split(r"[,\s;]+", raw):
        value = part.strip()
        if value.isdigit():
            ids.add(int(value))
    return ids


def _ensure_miniapp_enabled() -> None:
    if not is_miniapp_enabled():
        raise HTTPException(status_code=503, detail="Mini App is temporarily disabled for maintenance")


def _ensure_admin(session: dict[str, Any]) -> None:
    admin_ids = _parse_admin_ids()
    telegram_id = int(session["telegram_id"])
    if telegram_id not in admin_ids:
        raise HTTPException(status_code=403, detail="Admin privileges required")


def _format_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    if index == 0:
        return f"{int(size)} {units[index]}"
    return f"{size:.2f} {units[index]}"


def _verify_telegram_init_data(init_data: str) -> dict[str, Any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="initData is required")

    normalized_init_data = init_data.strip()
    if normalized_init_data.startswith("?"):
        normalized_init_data = normalized_init_data[1:]
    parsed = dict(parse_qsl(normalized_init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Invalid initData hash")
    received_hash = received_hash.strip().lower()
    if len(received_hash) != 64:
        raise HTTPException(status_code=401, detail="Invalid initData hash")

    check_data = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", _bot_token().encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_data.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid initData hash")

    auth_date = int(parsed.get("auth_date", "0") or "0")
    if auth_date <= 0 or int(time.time()) - auth_date > TELEGRAM_INITDATA_TTL_SECONDS:
        raise HTTPException(status_code=401, detail="initData expired")

    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Telegram user is missing")

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Invalid Telegram user") from None
    if not isinstance(user, dict) or "id" not in user:
        raise HTTPException(status_code=401, detail="Invalid Telegram user")
    return user


def _create_session(tg_user: dict[str, Any]) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "telegram_id": int(tg_user["id"]),
        "username": tg_user.get("username"),
        "expires_at": int(time.time()) + SESSION_TTL_SECONDS,
    }
    return token


def _clean_sessions() -> None:
    now_ts = int(time.time())
    expired = [token for token, payload in _sessions.items() if int(payload.get("expires_at", 0)) <= now_ts]
    for token in expired:
        _sessions.pop(token, None)


def _extract_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return authorization.replace("Bearer ", "", 1).strip()


def _current_session(authorization: Optional[str] = Header(default=None)) -> dict[str, Any]:
    _clean_sessions()
    token = _extract_token(authorization)
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid session")
    return session


def _days_left(expires_at: Optional[str]) -> int:
    if not expires_at:
        return 0
    try:
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((dt - datetime.now(timezone.utc)).total_seconds() // 86400))
    except Exception:
        return 0


def _resolve_main_key(telegram_id: int) -> Optional[dict[str, Any]]:
    keys = get_user_keys_for_display(telegram_id)
    if not keys:
        return None
    active_keys = [k for k in keys if k.get("is_active")]
    return active_keys[0] if active_keys else keys[0]


def _extract_bot_username() -> str:
    from urllib.parse import urlparse

    parsed = urlparse(BOT_RETURN_URL)
    path = (parsed.path or "").strip("/")
    if path:
        return path.split("/", 1)[0]
    return "BobrikVPNbot"


def _build_referral_link(user_id: int) -> str:
    code = ensure_user_referral_code(user_id)
    return f"https://t.me/{_extract_bot_username()}?start=ref{code}"


def _serialize_promocode_state(telegram_id: int) -> Dict[str, Any]:
    sale = get_flash_sale_state()
    global_code = str(sale.get("promo_code") or "").strip().upper()
    global_discount_pct = 0
    if sale.get("active"):
        base_price = int(sale.get("base_price_rub") or 0)
        sale_price = int(sale.get("sale_price_rub") or 0)
        if base_price > 0 and sale_price > 0 and sale_price < base_price:
            global_discount_pct = int(round(((base_price - sale_price) / base_price) * 100))

    active_user = get_user_active_promocode(telegram_id) or {}
    user_code = str(active_user.get("promo_code") or "").strip().upper()
    promo = get_promocode(user_code) if user_code else None
    if promo and int(promo.get("is_active") or 0) != 1:
        promo = None
        user_code = ""

    result: Dict[str, Any] = {
        "global": {
            "active": bool(sale.get("active") and global_code),
            "code": global_code if sale.get("active") else "",
            "discount_percent": global_discount_pct,
            "remaining_seconds": int(sale.get("remaining_seconds") or 0),
        },
        "active": None,
    }

    if user_code:
        result["active"] = {
            "code": user_code,
            "scope": str((promo or {}).get("visibility") or active_user.get("visibility") or "HIDDEN").upper(),
            "source": str(active_user.get("source") or "manual"),
        }
    elif result["global"]["active"]:
        result["active"] = {
            "code": global_code,
            "scope": "PUBLIC",
            "source": "flash_sale",
        }
    return result


def _build_key_copy_value(key: Optional[dict[str, Any]]) -> str:
    if not key:
        return ""
    direct = str(key.get("subscription_url") or "").strip()
    if direct:
        return direct

    token = str(key.get("split_config_token") or "").strip()
    base = get_split_config_public_base_url().strip().rstrip("/")
    if token and base:
        return f"{base}/split/{token}?format=link"

    email = str(key.get("panel_email") or "").strip()
    if email:
        return email

    uuid = str(key.get("client_uuid") or "").strip()
    if uuid:
        return uuid
    return ""


async def _resolve_key_link_for_user(telegram_id: int) -> str:
    key = _resolve_main_key(telegram_id)
    link = _build_key_copy_value(key)
    if link and not re.fullmatch(r"user_[A-Za-z0-9_\\-]+", link):
        return link

    if key and key.get("server_id") and key.get("panel_email"):
        try:
            client = await get_client(int(key["server_id"]))
            cfg = await client.get_client_config(str(key["panel_email"]))
            if cfg:
                generated = generate_link(cfg)
                if generated:
                    return generated
        except Exception as exc:
            logger.warning("Failed to generate live key link for telegram_id=%s: %s", telegram_id, exc)

    return link or ""


async def _resolve_key_link_for_key(telegram_id: int, key_id: int) -> str:
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    link = _build_key_copy_value(key)
    if link and not re.fullmatch(r"user_[A-Za-z0-9_\\-]+", link):
        return link

    if key.get("server_id") and key.get("panel_email"):
        try:
            client = await get_client(int(key["server_id"]))
            cfg = await client.get_client_config(str(key["panel_email"]))
            if cfg:
                generated = generate_link(cfg)
                if generated:
                    return generated
        except Exception as exc:
            logger.warning("Failed to generate key link for key_id=%s telegram_id=%s: %s", key_id, telegram_id, exc)

    return link or ""


def _admin_ticket_reply_markup(ticket_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": f"💬 Ответить #{ticket_id}", "callback_data": f"admin_ticket_reply:{ticket_id}"},
                {"text": "✅ Закрыть", "callback_data": f"admin_ticket_close:{ticket_id}"},
            ]
        ]
    }


async def _notify_admins_about_ticket_message(
    ticket_id: int,
    user_telegram_id: int,
    username: Optional[str],
    text: str,
) -> None:
    admin_ids = _parse_admin_ids()
    if not admin_ids:
        return

    bot_token = _normalize_secret(os.getenv("BOT_TOKEN", ""))
    if not bot_token:
        try:
            bot_token = _bot_token()
        except Exception as exc:
            logger.warning("Cannot notify admins about support ticket #%s: %s", ticket_id, exc)
            return
    if not bot_token:
        return

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    safe_username = html.escape(username or "no_username")
    safe_text = html.escape(text)
    message = (
        f"🎫 <b>Новый запрос в тикете #{ticket_id}</b>\n\n"
        f"👤 User ID: <code>{user_telegram_id}</code>\n"
        f"👤 Username: @{safe_username}\n\n"
        f"💬 <b>Сообщение:</b>\n{safe_text}"
    )
    reply_markup = _admin_ticket_reply_markup(ticket_id)
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as http:
        for admin_id in admin_ids:
            payload = {
                "chat_id": int(admin_id),
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
                "disable_web_page_preview": True,
            }
            try:
                async with http.post(api_url, json=payload) as response:
                    body_text = await response.text()
                    if response.status >= 400:
                        logger.warning(
                            "Failed to notify admin %s for ticket #%s: status=%s body=%s",
                            admin_id,
                            ticket_id,
                            response.status,
                            body_text,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to notify admin %s for ticket #%s: %s",
                    admin_id,
                    ticket_id,
                    exc,
                )


def _serialize_user_info(telegram_id: int, username: Optional[str]) -> dict[str, Any]:
    user, _ = get_or_create_user(telegram_id, username)
    all_keys = get_user_keys_for_display(telegram_id)
    key = _resolve_main_key(telegram_id)
    days = _days_left(key.get("expires_at") if key else None)
    status = "active" if key and key.get("is_active") else "expired"
    admin_ids = _parse_admin_ids()
    key_copy = _build_key_copy_value(key)
    return {
        "telegram_id": telegram_id,
        "username": username,
        "balance_rub": round(get_user_balance(user["id"]) / 100, 2),
        "days_left": days,
        "status": status,
        "key": key_copy or None,
        "key_id": key.get("id") if key else None,
        "display_name": key.get("display_name") if key else None,
        "expires_at": key.get("expires_at") if key else None,
        "referral_link": _build_referral_link(user["id"]),
        "active_keys": sum(1 for item in all_keys if item.get("is_active")),
        "keys_total": len(all_keys),
        "is_admin": telegram_id in admin_ids,
        "miniapp_enabled": is_miniapp_enabled(),
    }


def _remove_ru_defaults_for_key(telegram_id: int, key_id: int) -> None:
    defaults = {(item["rule_type"], item["rule_value"]) for item in get_default_ru_exclusions()}
    if not defaults:
        return
    with get_db() as conn:
        for rule_type, rule_value in defaults:
            conn.execute(
                """
                DELETE FROM key_exclusions
                WHERE key_id = ?
                  AND rule_type = ?
                  AND rule_value = ?
                  AND key_id IN (
                    SELECT vk.id
                    FROM vpn_keys vk
                    JOIN users u ON u.id = vk.user_id
                    WHERE u.telegram_id = ?
                  )
                """,
                (key_id, rule_type, rule_value, telegram_id),
            )


@app.get("/api/app_state")
def app_state() -> dict[str, Any]:
    return {"ok": True, "data": {"miniapp_enabled": is_miniapp_enabled()}}


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.post("/api/auth/session")
def auth_session(payload: SessionRequest) -> dict[str, Any]:
    tg_user = _verify_telegram_init_data(payload.initData)
    session_token = _create_session(tg_user)
    return {
        "ok": True,
        "token": session_token,
        "user": _serialize_user_info(int(tg_user["id"]), tg_user.get("username")),
    }


@app.get("/api/get_user_info")
def get_user_info(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    return {
        "ok": True,
        "data": _serialize_user_info(int(session["telegram_id"]), session.get("username")),
    }


@app.get("/api/promocode_state")
def promocode_state(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    return {"ok": True, "data": _serialize_promocode_state(telegram_id)}


@app.get("/api/key_link")
async def get_key_link(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    link = await _resolve_key_link_for_user(telegram_id)
    if not link:
        raise HTTPException(status_code=404, detail="Key link not found")
    return {"ok": True, "data": {"key_link": link}}


@app.get("/api/keys")
def list_keys(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    keys = get_user_keys_for_display(telegram_id)
    data = []
    for item in keys:
        traffic_used = int(item.get("traffic_used") or 0)
        traffic_limit = int(item.get("traffic_limit") or 0)
        remaining = max(0, traffic_limit - traffic_used) if traffic_limit > 0 else 0
        data.append(
            {
                "id": int(item["id"]),
                "display_name": item.get("display_name"),
                "custom_name": item.get("custom_name"),
                "server_name": item.get("server_name"),
                "server_id": item.get("server_id"),
                "is_active": bool(item.get("is_active")),
                "expires_at": item.get("expires_at"),
                "traffic_used_bytes": traffic_used,
                "traffic_limit_bytes": traffic_limit,
                "traffic_remaining_bytes": remaining if traffic_limit > 0 else None,
                "traffic_used_human": _format_bytes(traffic_used),
                "traffic_limit_human": "Unlimited" if traffic_limit <= 0 else _format_bytes(traffic_limit),
                "traffic_remaining_human": "Unlimited" if traffic_limit <= 0 else _format_bytes(remaining),
            }
        )
    return {"ok": True, "data": data}


@app.get("/api/keys/{key_id}")
async def get_key_details_api(key_id: int, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")
    key_link = await _resolve_key_link_for_key(telegram_id, key_id)
    return {"ok": True, "data": {"key": key, "key_link": key_link}}


@app.get("/api/keys/{key_id}/link")
async def get_key_link_by_id(key_id: int, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    link = await _resolve_key_link_for_key(telegram_id, key_id)
    if not link:
        raise HTTPException(status_code=404, detail="Key link not found")
    return {"ok": True, "data": {"key_link": link}}


@app.post("/api/keys/{key_id}/rename")
def rename_key(key_id: int, payload: RenameKeyRequest, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    new_name = (payload.name or "").strip()
    if len(new_name) > 30:
        raise HTTPException(status_code=400, detail="Name must be 30 characters or less")

    success = update_key_custom_name(key_id, telegram_id, new_name)
    if not success:
        raise HTTPException(status_code=404, detail="Key not found or rename failed")
    key = get_key_details_for_user(key_id, telegram_id)
    return {"ok": True, "data": {"key": key}}


@app.get("/api/get_tariffs")
def get_tariffs(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    _ = session
    tariffs = get_all_tariffs(include_hidden=False)
    data = []
    for tariff in tariffs:
        price_rub = int(float(tariff.get("price_rub") or 0))
        if price_rub <= 0:
            continue
        data.append(
            {
                "id": tariff["id"],
                "name": tariff["name"],
                "days": int(tariff.get("duration_days") or 0),
                "price_rub": price_rub,
            }
        )
    return {"ok": True, "data": data}


@app.post("/api/create_invoice")
async def create_invoice(payload: InvoiceRequest, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    if not is_platega_ready():
        raise HTTPException(status_code=400, detail="Platega disabled")

    method_code = payload.method.strip().lower()
    if method_code not in {"sbp", "card", "crypto"}:
        raise HTTPException(status_code=400, detail="Unsupported payment method")
    if not is_platega_method_enabled(method_code):
        raise HTTPException(status_code=400, detail="Payment method is disabled")

    tariff = get_tariff_by_id(payload.tariff_id)
    if not tariff:
        raise HTTPException(status_code=404, detail="Tariff not found")

    price_rub = int(float(tariff.get("price_rub") or 0))
    if price_rub <= 0:
        raise HTTPException(status_code=400, detail="Tariff RUB price is invalid")

    telegram_id = int(session["telegram_id"])
    user, _ = get_or_create_user(telegram_id, session.get("username"))

    vpn_key_id = None
    if payload.key_id is not None:
        key = get_key_details_for_user(int(payload.key_id), telegram_id)
        if not key:
            raise HTTPException(status_code=404, detail="Key not found")
        vpn_key_id = int(payload.key_id)

    _id, order_id = create_pending_order(
        user_id=user["id"],
        tariff_id=int(payload.tariff_id),
        payment_type="platega",
        vpn_key_id=vpn_key_id,
    )

    selected_promo = ""
    promo_selected_explicitly = False
    if payload.use_promo:
        selected_promo = str(payload.promo_code or "").strip().upper()
        promo_selected_explicitly = bool(selected_promo)
        if not selected_promo:
            active_user = get_user_active_promocode(telegram_id) or {}
            selected_promo = str(active_user.get("promo_code") or "").strip().upper()
        if not selected_promo:
            sale = get_flash_sale_state()
            if sale.get("active"):
                selected_promo = str(sale.get("promo_code") or "").strip().upper()

    final_price_rub = price_rub
    discount_rub = 0
    applied_promo_code: Optional[str] = None
    if selected_promo:
        promo_ok, promo_payload, promo_err = apply_promocode_to_order(
            order_id,
            user["id"],
            selected_promo,
            price_rub,
            telegram_id=telegram_id,
        )
        if promo_ok and promo_payload:
            final_price_rub = int(promo_payload.get("final_amount") or price_rub)
            discount_rub = int(promo_payload.get("discount_amount") or 0)
            applied_promo_code = str(promo_payload.get("code") or "").strip().upper() or None
            if applied_promo_code:
                set_user_active_promocode(telegram_id, applied_promo_code, source="miniapp")
        elif promo_selected_explicitly:
            raise HTTPException(status_code=400, detail=promo_err or "Promo code is invalid")
        else:
            clear_user_active_promocode(telegram_id)

    create_or_update_transaction(
        order_id=order_id,
        user_id=user["id"],
        amount=final_price_rub,
        currency="RUB",
        status="PENDING",
        payload={
            "kind": "miniapp_platega_checkout",
            "method": method_code,
            "tariff_name": tariff.get("name"),
            "key_id": vpn_key_id,
            "base_amount_rub": price_rub,
            "discount_amount_rub": discount_rub,
            "promo_code": applied_promo_code,
        },
    )

    platega_method = get_platega_payment_method_id(method_code)
    try:
        result = await create_payment_link(
            amount_rub=final_price_rub,
            order_id=order_id,
            description=f"Оплата тарифа {tariff.get('name')}",
            success_url=BOT_RETURN_URL,
            fail_url=BOT_RETURN_URL,
            payment_method=platega_method,
            method_code_hint=method_code,
        )
    except Exception as exc:
        update_transaction_status(
            order_id=order_id,
            status="FAILED",
            payload={
                "kind": "miniapp_platega_checkout",
                "method": method_code,
                "tariff_name": tariff.get("name"),
                "key_id": vpn_key_id,
                "error": str(exc),
            },
        )
        logger.warning("Failed to create Platega link for order %s: %s", order_id, exc)
        raise HTTPException(status_code=502, detail="Failed to create Platega link") from exc

    create_or_update_transaction(
        order_id=order_id,
        user_id=user["id"],
        amount=final_price_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload={
            "kind": "miniapp_platega_checkout",
            "method": method_code,
            "tariff_name": tariff.get("name"),
            "key_id": vpn_key_id,
            "base_amount_rub": price_rub,
            "discount_amount_rub": discount_rub,
            "promo_code": applied_promo_code,
            "provider": result.get("raw"),
        },
    )

    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "redirect_url": result["redirect_url"],
            "transaction_id": result["transaction_id"],
            "amount_rub": final_price_rub,
            "base_amount_rub": price_rub,
            "discount_amount_rub": discount_rub,
            "promo_code": applied_promo_code,
        },
    }


@app.post("/api/set_ru_bypass")
def set_ru_bypass(payload: RuBypassRequest, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    key = get_key_details_for_user(payload.key_id, telegram_id)
    if not key:
        raise HTTPException(status_code=404, detail="Key not found")

    if payload.enabled:
        inserted = 0
        for item in get_default_ru_exclusions():
            if add_key_exclusion_for_user(payload.key_id, telegram_id, item["rule_type"], item["rule_value"]):
                inserted += 1
        return {"ok": True, "data": {"enabled": True, "inserted": inserted}}

    _remove_ru_defaults_for_key(telegram_id, payload.key_id)
    return {"ok": True, "data": {"enabled": False}}


@app.get("/api/subscription/stats")
def subscription_stats(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    keys = get_user_keys_for_display(telegram_id)
    data = []
    for key in keys:
        traffic_used = int(key.get("traffic_used") or 0)
        traffic_limit = int(key.get("traffic_limit") or 0)
        remaining = max(0, traffic_limit - traffic_used) if traffic_limit > 0 else 0
        data.append(
            {
                "id": key["id"],
                "display_name": key.get("display_name"),
                "status": "active" if key.get("is_active") else "expired",
                "traffic_used_bytes": traffic_used,
                "traffic_limit_bytes": traffic_limit,
                "traffic_remaining_bytes": remaining if traffic_limit > 0 else None,
                "traffic_used_human": _format_bytes(traffic_used),
                "traffic_limit_human": "Unlimited" if traffic_limit <= 0 else _format_bytes(traffic_limit),
                "traffic_remaining_human": "Unlimited" if traffic_limit <= 0 else _format_bytes(remaining),
                "expires_at": key.get("expires_at"),
                "server_name": key.get("server_name"),
            }
        )
    return {"ok": True, "data": data}


@app.get("/api/referrals")
def referral_data(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    username = session.get("username")
    user, _ = get_or_create_user(telegram_id, username)
    invites = get_direct_referrals_with_purchase_info(user["id"], limit=30)
    return {
        "ok": True,
        "data": {
            "enabled": is_referral_enabled(),
            "reward_type": get_referral_reward_type(),
            "levels": get_active_referral_levels(),
            "stats": get_referral_stats(user["id"]),
            "direct_invites": invites,
            "direct_total": count_direct_referrals(user["id"]),
            "direct_paid": count_direct_paid_referrals(user["id"]),
            "referral_link": _build_referral_link(user["id"]),
        },
    }


@app.get("/api/support")
def get_support_ticket(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    user, _ = get_or_create_user(telegram_id, session.get("username"))
    ticket = get_open_ticket_for_user(user["id"])
    messages: list[dict[str, Any]] = []
    if ticket:
        messages = get_ticket_messages(int(ticket["id"]), limit=100)
    history = list_user_tickets(user["id"], status=None, limit=30)
    closed = [item for item in history if item.get("status") == "closed"]
    open_items = [item for item in history if item.get("status") == "open"]

    admin_history: list[dict[str, Any]] = []
    if telegram_id in _parse_admin_ids():
        admin_history = list_admin_tickets(status=None, limit=50)
    return {
        "ok": True,
        "data": {
            "ticket": ticket,
            "messages": messages,
            "history": history,
            "open_tickets": open_items,
            "closed_tickets": closed,
            "admin_history": admin_history,
        },
    }


@app.get("/api/support/ticket/{ticket_id}")
def get_support_ticket_by_id(ticket_id: int, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    telegram_id = int(session["telegram_id"])
    user, _ = get_or_create_user(telegram_id, session.get("username"))
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    is_admin = telegram_id in _parse_admin_ids()
    if not is_admin and int(ticket.get("user_id") or 0) != int(user["id"]):
        raise HTTPException(status_code=403, detail="Forbidden")

    messages = get_ticket_messages(ticket_id, limit=200)
    return {"ok": True, "data": {"ticket": ticket, "messages": messages}}


@app.post("/api/support")
async def post_support_ticket(payload: SupportTicketRequest, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_miniapp_enabled()
    text = (payload.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is required")
    if len(text) > 1500:
        raise HTTPException(status_code=400, detail="Message is too long")

    telegram_id = int(session["telegram_id"])
    user, _ = get_or_create_user(telegram_id, session.get("username"))
    ticket = get_open_ticket_for_user(user["id"])
    if ticket:
        ticket_id = int(ticket["id"])
    else:
        ticket_id = create_support_ticket(
            user_id=user["id"],
            user_telegram_id=telegram_id,
            username=session.get("username"),
        )
    add_ticket_message(ticket_id=ticket_id, sender_role="user", sender_telegram_id=telegram_id, text=text)
    await _notify_admins_about_ticket_message(
        ticket_id=ticket_id,
        user_telegram_id=telegram_id,
        username=session.get("username"),
        text=text,
    )
    return {"ok": True, "data": {"ticket_id": ticket_id}}


@app.get("/api/admin/miniapp_state")
def get_admin_miniapp_state(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
    _ensure_admin(session)
    return {"ok": True, "data": {"miniapp_enabled": is_miniapp_enabled()}}


@app.post("/api/admin/miniapp_state")
def set_admin_miniapp_state(
    payload: AdminMiniAppToggleRequest,
    session: dict[str, Any] = Depends(_current_session),
) -> dict[str, Any]:
    _ensure_admin(session)
    set_miniapp_enabled(bool(payload.enabled))
    return {"ok": True, "data": {"miniapp_enabled": is_miniapp_enabled()}}


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled backend error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "detail": "Internal server error",
        },
    )


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
