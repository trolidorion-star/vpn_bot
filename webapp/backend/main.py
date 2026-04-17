import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from bot.services.platega_client import (
    create_payment_link,
    get_platega_payment_method_id,
    is_platega_method_enabled,
    is_platega_ready,
)
from bot.services.ru_bypass import get_default_ru_exclusions
from database.connection import get_db
from database.requests import (
    add_key_exclusion_for_user,
    create_or_update_transaction,
    create_pending_order,
    get_all_tariffs,
    get_key_details_for_user,
    get_or_create_user,
    get_tariff_by_id,
    get_user_balance,
    get_user_keys_for_display,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "webapp" / "frontend"
BOT_RETURN_URL = os.getenv("BOT_RETURN_URL", "https://t.me/BobrikVPNbot")
SESSION_TTL_SECONDS = int(os.getenv("MINI_APP_SESSION_TTL", "21600"))

app = FastAPI(title="Bobrik Mini App API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict[str, dict[str, Any]] = {}


class SessionRequest(BaseModel):
    initData: str


class InvoiceRequest(BaseModel):
    tariff_id: int
    method: str
    key_id: Optional[int] = None


class RuBypassRequest(BaseModel):
    key_id: int
    enabled: bool


def _bot_token() -> str:
    token = os.getenv("BOT_TOKEN", "").strip()
    if token:
        return token
    raise RuntimeError("BOT_TOKEN is required")


def _verify_telegram_init_data(init_data: str) -> dict[str, Any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="initData is required")

    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Invalid initData hash")

    check_data = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", _bot_token().encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_data.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid initData hash")

    auth_date = int(parsed.get("auth_date", "0") or "0")
    if auth_date <= 0 or int(time.time()) - auth_date > 24 * 60 * 60:
        raise HTTPException(status_code=401, detail="initData expired")

    user_raw = parsed.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Telegram user is missing")

    user = json.loads(user_raw)
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


def _serialize_user_info(telegram_id: int, username: Optional[str]) -> dict[str, Any]:
    user, _ = get_or_create_user(telegram_id, username)
    key = _resolve_main_key(telegram_id)
    days = _days_left(key.get("expires_at") if key else None)
    status = "active" if key and key.get("is_active") else "expired"
    return {
        "telegram_id": telegram_id,
        "username": username,
        "balance_rub": round(get_user_balance(user["id"]) / 100, 2),
        "days_left": days,
        "status": status,
        "key": key.get("subscription_url") if key else None,
        "key_id": key.get("id") if key else None,
        "display_name": key.get("display_name") if key else None,
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


@app.get("/api/get_tariffs")
def get_tariffs(session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
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

    create_or_update_transaction(
        order_id=order_id,
        user_id=user["id"],
        amount=price_rub,
        currency="RUB",
        status="PENDING",
        payload={
            "kind": "miniapp_platega_checkout",
            "method": method_code,
            "tariff_name": tariff.get("name"),
            "key_id": vpn_key_id,
        },
    )

    platega_method = get_platega_payment_method_id(method_code)
    result = await create_payment_link(
        amount_rub=price_rub,
        order_id=order_id,
        description=f"Оплата тарифа {tariff.get('name')}",
        success_url=BOT_RETURN_URL,
        fail_url=BOT_RETURN_URL,
        payment_method=platega_method,
    )

    create_or_update_transaction(
        order_id=order_id,
        user_id=user["id"],
        amount=price_rub,
        currency="RUB",
        payment_id=result["transaction_id"],
        status="PENDING",
        payload={
            "kind": "miniapp_platega_checkout",
            "method": method_code,
            "tariff_name": tariff.get("name"),
            "key_id": vpn_key_id,
            "provider": result.get("raw"),
        },
    )

    return {
        "ok": True,
        "data": {
            "order_id": order_id,
            "redirect_url": result["redirect_url"],
            "transaction_id": result["transaction_id"],
        },
    }


@app.post("/api/set_ru_bypass")
def set_ru_bypass(payload: RuBypassRequest, session: dict[str, Any] = Depends(_current_session)) -> dict[str, Any]:
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


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
