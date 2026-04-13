import base64
import hashlib
import hmac
import json
import logging
import math
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl

from aiohttp import web

from config import BOT_TOKEN
from bot.services.key_limits import get_key_connection_limit
from bot.services.mini_app_settings import (
    get_mini_app_bind_host,
    get_mini_app_bind_port,
    get_mini_app_enabled,
    get_mini_app_public_url,
    get_mini_app_session_ttl_seconds,
)
from bot.services.split_config_settings import get_split_config_public_url
from bot.services.user_locks import user_locks
from bot.services.vpn_api import get_client, push_key_to_panel
from bot.utils.groups import get_servers_for_key
from bot.utils.key_generator import generate_json, generate_link, generate_qr_code
from database.requests import (
    complete_order,
    create_initial_vpn_key,
    create_pending_order,
    deduct_from_balance,
    ensure_split_config_token_for_user,
    extend_vpn_key,
    get_active_servers,
    get_all_tariffs,
    get_key_details_for_user,
    get_or_create_user,
    get_referral_reward_type,
    get_server_by_id,
    get_setting,
    get_tariff_by_id,
    get_trial_tariff_id,
    get_user_balance,
    get_user_keys_for_display,
    has_used_trial,
    is_crypto_configured,
    is_referral_enabled,
    is_trial_enabled,
    is_user_banned,
    mark_trial_used,
    set_key_expiration_hours,
    update_vpn_key_config,
)

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None
_sessions: Dict[str, Dict[str, Any]] = {}

_ROOT_DIR = Path(__file__).resolve().parents[2]
_WEBAPP_DIR = _ROOT_DIR / "miniapp"
_WEBAPP_STATIC = _WEBAPP_DIR / "static"


def _cache_headers() -> Dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _gen_panel_email(user: Dict[str, Any]) -> str:
    base = f"user_{user['username']}" if user.get("username") else f"user_{user['telegram_id']}"
    return f"{base}_{uuid.uuid4().hex[:5]}"


def _verify_telegram_init_data(init_data: str) -> Optional[Dict[str, Any]]:
    if not init_data:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    check_data = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, check_data.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    auth_date_raw = parsed.get("auth_date", "0")
    try:
        auth_date = int(auth_date_raw)
    except Exception:
        auth_date = 0
    if auth_date <= 0:
        return None
    if int(time.time()) - auth_date > 24 * 60 * 60:
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        tg_user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(tg_user, dict) or "id" not in tg_user:
        return None
    return tg_user


def _purge_expired_sessions() -> None:
    now_ts = time.time()
    expired = [token for token, data in _sessions.items() if data.get("expires_at", 0) <= now_ts]
    for token in expired:
        _sessions.pop(token, None)


def _create_session(user_data: Dict[str, Any]) -> str:
    _purge_expired_sessions()
    token = secrets.token_urlsafe(32)
    ttl = get_mini_app_session_ttl_seconds()
    _sessions[token] = {
        "telegram_id": int(user_data["id"]),
        "username": user_data.get("username"),
        "first_name": user_data.get("first_name"),
        "last_name": user_data.get("last_name"),
        "expires_at": time.time() + ttl,
    }
    return token


def _session_from_request(request: web.Request) -> Optional[Dict[str, Any]]:
    _purge_expired_sessions()
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.replace("Bearer ", "", 1).strip()
    if not token:
        return None
    session = _sessions.get(token)
    if not session:
        return None
    if session.get("expires_at", 0) <= time.time():
        _sessions.pop(token, None)
        return None
    return session


def _as_rub_text(cents: int) -> str:
    rub = cents / 100
    return f"{rub:.2f}".replace(".", ",")


def _build_keys_payload(keys: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    prepared = []
    now = datetime.now(timezone.utc)
    for key in keys:
        expires_at = key.get("expires_at")
        days_left = None
        if expires_at:
            try:
                dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_left = max(0, math.ceil((dt - now).total_seconds() / 86400))
            except Exception:
                days_left = None
        traffic_used = int(key.get("traffic_used") or 0)
        traffic_limit = int(key.get("traffic_limit") or 0)
        traffic_percent = 0.0
        if traffic_limit > 0:
            traffic_percent = min(100.0, round((traffic_used / traffic_limit) * 100, 1))

        prepared.append(
            {
                "id": key["id"],
                "display_name": key.get("display_name") or f"Key #{key['id']}",
                "server_name": key.get("server_name"),
                "server_id": key.get("server_id"),
                "panel_email": key.get("panel_email"),
                "is_active": bool(key.get("is_active")),
                "expires_at": key.get("expires_at"),
                "days_left": days_left,
                "traffic_used": traffic_used,
                "traffic_limit": traffic_limit,
                "traffic_percent": traffic_percent,
                "is_draft": not bool(key.get("server_id")),
            }
        )
    return prepared


def _can_use_balance() -> bool:
    return is_referral_enabled() and get_referral_reward_type() == "balance"


async def _bootstrap_payload(telegram_id: int, username: Optional[str]) -> Dict[str, Any]:
    user, _ = get_or_create_user(telegram_id, username)
    keys = get_user_keys_for_display(telegram_id)
    tariffs = get_all_tariffs(include_hidden=False)
    trial_tariff_id = get_trial_tariff_id()
    trial_available = (
        is_trial_enabled()
        and trial_tariff_id is not None
        and not has_used_trial(telegram_id)
        and get_tariff_by_id(trial_tariff_id) is not None
    )
    balance_cents = get_user_balance(user["id"])

    mini_app_name = get_setting("mini_app_name", "VPN Control Center")
    crypto_enabled = is_crypto_configured()
    crypto_mode = get_setting("crypto_integration_mode", "standard")

    return {
        "user": {
            "telegram_id": telegram_id,
            "username": username,
            "internal_id": user["id"],
            "balance_cents": balance_cents,
            "balance_text": _as_rub_text(balance_cents),
        },
        "app": {
            "name": mini_app_name,
            "crypto_enabled": bool(crypto_enabled),
            "crypto_mode": crypto_mode,
            "can_use_balance": _can_use_balance(),
            "split_base_enabled": bool(get_setting("split_config_public_base_url", "")),
        },
        "trial": {
            "available": trial_available,
            "tariff_id": trial_tariff_id,
        },
        "tariffs": tariffs,
        "keys": _build_keys_payload(keys),
    }


async def _json(request: web.Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            return {}
        return payload
    except Exception:
        return {}


async def _index_handler(_: web.Request) -> web.Response:
    index_path = _WEBAPP_DIR / "index.html"
    if not index_path.exists():
        return web.Response(text="Mini app assets not found", status=404)
    return web.FileResponse(index_path, headers=_cache_headers())


async def _health_handler(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"}, headers=_cache_headers())


async def _session_handler(request: web.Request) -> web.Response:
    payload = await _json(request)
    init_data = str(payload.get("initData") or "").strip()
    tg_user = _verify_telegram_init_data(init_data)
    if not tg_user:
        return web.json_response({"ok": False, "error": "invalid initData"}, status=401, headers=_cache_headers())

    telegram_id = int(tg_user["id"])
    if is_user_banned(telegram_id):
        return web.json_response({"ok": False, "error": "access denied"}, status=403, headers=_cache_headers())

    token = _create_session(tg_user)
    bootstrap = await _bootstrap_payload(telegram_id, tg_user.get("username"))
    return web.json_response(
        {"ok": True, "token": token, "bootstrap": bootstrap},
        headers=_cache_headers(),
    )


async def _bootstrap_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())
    telegram_id = int(session["telegram_id"])
    bootstrap = await _bootstrap_payload(telegram_id, session.get("username"))
    return web.json_response({"ok": True, "data": bootstrap}, headers=_cache_headers())


async def _trial_activate_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())

    telegram_id = int(session["telegram_id"])
    if not is_trial_enabled():
        return web.json_response({"ok": False, "error": "trial disabled"}, status=400, headers=_cache_headers())
    trial_tariff_id = get_trial_tariff_id()
    if trial_tariff_id is None:
        return web.json_response({"ok": False, "error": "trial tariff is not configured"}, status=400, headers=_cache_headers())
    if has_used_trial(telegram_id):
        return web.json_response({"ok": False, "error": "trial already used"}, status=409, headers=_cache_headers())

    tariff = get_tariff_by_id(trial_tariff_id)
    if not tariff:
        return web.json_response({"ok": False, "error": "trial tariff not found"}, status=404, headers=_cache_headers())

    user, _ = get_or_create_user(telegram_id, session.get("username"))
    mark_trial_used(user["id"])
    duration_days = int(tariff.get("duration_days") or 1)
    traffic_limit_bytes = int((tariff.get("traffic_limit_gb") or 0) * 1024 ** 3)
    key_id = create_initial_vpn_key(user["id"], trial_tariff_id, duration_days, traffic_limit=traffic_limit_bytes)
    trial_hours_override = int(get_setting("trial_duration_hours_override", "1") or "1")
    if trial_hours_override > 0:
        set_key_expiration_hours(key_id, trial_hours_override)

    _, order_id = create_pending_order(
        user_id=user["id"],
        tariff_id=trial_tariff_id,
        payment_type="trial",
        vpn_key_id=key_id,
    )
    complete_order(order_id)

    bootstrap = await _bootstrap_payload(telegram_id, session.get("username"))
    return web.json_response(
        {"ok": True, "data": {"order_id": order_id, "key_id": key_id}, "bootstrap": bootstrap},
        headers=_cache_headers(),
    )


async def _balance_purchase_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())
    if not _can_use_balance():
        return web.json_response({"ok": False, "error": "balance payments disabled"}, status=403, headers=_cache_headers())

    payload = await _json(request)
    try:
        tariff_id = int(payload.get("tariff_id"))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid tariff_id"}, status=400, headers=_cache_headers())
    key_id_raw = payload.get("key_id")
    key_id = int(key_id_raw) if str(key_id_raw or "").isdigit() else None

    telegram_id = int(session["telegram_id"])
    user, _ = get_or_create_user(telegram_id, session.get("username"))
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return web.json_response({"ok": False, "error": "tariff not found"}, status=404, headers=_cache_headers())

    tariff_price_cents = int((tariff.get("price_rub") or 0) * 100)
    if tariff_price_cents <= 0:
        return web.json_response({"ok": False, "error": "tariff has no RUB price"}, status=400, headers=_cache_headers())

    if key_id is not None:
        key = get_key_details_for_user(key_id, telegram_id)
        if not key:
            return web.json_response({"ok": False, "error": "key not found"}, status=404, headers=_cache_headers())

    days = int(tariff.get("duration_days") or 30)
    created_key_id = key_id
    order_id = ""
    async with user_locks[user["id"]]:
        current_balance = get_user_balance(user["id"])
        if current_balance < tariff_price_cents:
            return web.json_response({"ok": False, "error": "insufficient balance"}, status=409, headers=_cache_headers())
        if not deduct_from_balance(user["id"], tariff_price_cents):
            return web.json_response({"ok": False, "error": "failed to deduct balance"}, status=409, headers=_cache_headers())

        if key_id is not None:
            extend_vpn_key(key_id, days)
            order_id = create_pending_order(
                user_id=user["id"], tariff_id=tariff_id, payment_type="balance", vpn_key_id=key_id
            )[1]
            complete_order(order_id)
            try:
                await push_key_to_panel(key_id, reset_traffic=True)
            except Exception as e:
                logger.warning("Mini app: failed to sync key %s to panel after renewal: %s", key_id, e)
        else:
            traffic_limit_bytes = int((tariff.get("traffic_limit_gb") or 0) * 1024 ** 3)
            created_key_id = create_initial_vpn_key(
                user["id"], tariff_id, days, traffic_limit=traffic_limit_bytes
            )
            _, order_id = create_pending_order(
                user_id=user["id"],
                tariff_id=tariff_id,
                payment_type="balance",
                vpn_key_id=created_key_id,
            )
            complete_order(order_id)

    bootstrap = await _bootstrap_payload(telegram_id, session.get("username"))
    return web.json_response(
        {
            "ok": True,
            "data": {"order_id": order_id, "key_id": created_key_id, "is_renewal": key_id is not None},
            "bootstrap": bootstrap,
        },
        headers=_cache_headers(),
    )


async def _key_material_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())

    key_id = int(request.match_info["key_id"])
    telegram_id = int(session["telegram_id"])
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        return web.json_response({"ok": False, "error": "key not found"}, status=404, headers=_cache_headers())
    if not key.get("server_id") or not key.get("panel_email"):
        return web.json_response(
            {"ok": True, "data": {"status": "draft", "key_id": key_id}},
            headers=_cache_headers(),
        )

    try:
        client = await get_client(int(key["server_id"]))
        cfg = await client.get_client_config(str(key["panel_email"]))
    except Exception as e:
        logger.error("Mini app: failed to load client config for key %s: %s", key_id, e)
        cfg = None

    if not cfg:
        return web.json_response({"ok": False, "error": "config unavailable"}, status=502, headers=_cache_headers())

    link = generate_link(cfg)
    json_config = generate_json(cfg)
    qr_bytes = generate_qr_code(link)
    qr_b64 = base64.b64encode(qr_bytes).decode("ascii")
    split_url = ""
    token = key.get("split_config_token") or ensure_split_config_token_for_user(key_id, telegram_id)
    if token:
        split_url = get_split_config_public_url(token)

    return web.json_response(
        {
            "ok": True,
            "data": {
                "status": "ready",
                "key_id": key_id,
                "link": link,
                "json_config": json_config,
                "qr_base64": qr_b64,
                "split_url": split_url,
            },
        },
        headers=_cache_headers(),
    )


async def _key_servers_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())

    key_id = int(request.match_info["key_id"])
    telegram_id = int(session["telegram_id"])
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        return web.json_response({"ok": False, "error": "key not found"}, status=404, headers=_cache_headers())

    tariff_id = key.get("tariff_id")
    servers = get_servers_for_key(tariff_id) if tariff_id else get_active_servers()
    payload = [{"id": s["id"], "name": s["name"]} for s in servers]
    return web.json_response({"ok": True, "data": payload}, headers=_cache_headers())


async def _server_inbounds_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())

    server_id = int(request.match_info["server_id"])
    server = get_server_by_id(server_id)
    if not server or not server.get("is_active"):
        return web.json_response({"ok": False, "error": "server not found"}, status=404, headers=_cache_headers())

    try:
        client = await get_client(server_id)
        inbounds = await client.get_inbounds()
        data = [{"id": item.get("id"), "remark": item.get("remark", "VPN")} for item in inbounds if item.get("id")]
    except Exception as e:
        logger.error("Mini app: failed to fetch inbounds for server %s: %s", server_id, e)
        return web.json_response({"ok": False, "error": "server unavailable"}, status=502, headers=_cache_headers())
    return web.json_response({"ok": True, "data": data}, headers=_cache_headers())


def _days_from_key_expiration(expires_at: Any) -> int:
    if not expires_at:
        return 30
    try:
        dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days = math.ceil((dt - now).total_seconds() / 86400)
        return max(1, days)
    except Exception:
        return 30


async def _provision_key_handler(request: web.Request) -> web.Response:
    session = _session_from_request(request)
    if not session:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401, headers=_cache_headers())

    key_id = int(request.match_info["key_id"])
    payload = await _json(request)
    try:
        server_id = int(payload.get("server_id"))
        inbound_id = int(payload.get("inbound_id"))
    except Exception:
        return web.json_response({"ok": False, "error": "invalid payload"}, status=400, headers=_cache_headers())

    telegram_id = int(session["telegram_id"])
    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        return web.json_response({"ok": False, "error": "key not found"}, status=404, headers=_cache_headers())
    if key.get("server_id") and key.get("panel_email"):
        return web.json_response({"ok": False, "error": "key already configured"}, status=409, headers=_cache_headers())

    server = get_server_by_id(server_id)
    if not server or not server.get("is_active"):
        return web.json_response({"ok": False, "error": "server not found"}, status=404, headers=_cache_headers())

    user = {"telegram_id": telegram_id, "username": session.get("username")}
    panel_email = _gen_panel_email(user)
    days = _days_from_key_expiration(key.get("expires_at"))
    try:
        tariff = get_tariff_by_id(int(key.get("tariff_id") or 0))
        traffic_limit_gb = int(tariff.get("traffic_limit_gb") or 0) if tariff else 0
    except Exception:
        traffic_limit_gb = 0

    connection_limit = get_key_connection_limit()
    try:
        client = await get_client(server_id)
        flow = await client.get_inbound_flow(inbound_id)
        result = await client.add_client(
            inbound_id=inbound_id,
            email=panel_email,
            total_gb=traffic_limit_gb,
            expire_days=days,
            limit_ip=connection_limit,
            enable=True,
            tg_id=str(telegram_id),
            flow=flow,
        )
        client_uuid = result["uuid"]
        update_vpn_key_config(
            key_id=key_id,
            server_id=server_id,
            panel_inbound_id=inbound_id,
            panel_email=panel_email,
            client_uuid=client_uuid,
        )
        try:
            await push_key_to_panel(key_id)
        except Exception as e:
            logger.warning("Mini app: failed to post-sync key %s: %s", key_id, e)
    except Exception as e:
        logger.error("Mini app: key provisioning failed for key %s: %s", key_id, e)
        return web.json_response({"ok": False, "error": "provisioning failed"}, status=502, headers=_cache_headers())

    bootstrap = await _bootstrap_payload(telegram_id, session.get("username"))
    return web.json_response(
        {"ok": True, "data": {"key_id": key_id}, "bootstrap": bootstrap},
        headers=_cache_headers(),
    )


def _app() -> web.Application:
    app = web.Application()
    app.add_routes(
        [
            web.get("/miniapp", _index_handler),
            web.get("/miniapp/", _index_handler),
            web.get("/miniapp/health", _health_handler),
            web.post("/miniapp/api/session", _session_handler),
            web.get("/miniapp/api/bootstrap", _bootstrap_handler),
            web.post("/miniapp/api/trial/activate", _trial_activate_handler),
            web.post("/miniapp/api/payments/balance", _balance_purchase_handler),
            web.get("/miniapp/api/keys/{key_id:\\d+}/material", _key_material_handler),
            web.get("/miniapp/api/keys/{key_id:\\d+}/servers", _key_servers_handler),
            web.get("/miniapp/api/servers/{server_id:\\d+}/inbounds", _server_inbounds_handler),
            web.post("/miniapp/api/keys/{key_id:\\d+}/provision", _provision_key_handler),
        ]
    )
    app.router.add_static("/miniapp/static/", path=str(_WEBAPP_STATIC), name="miniapp_static")
    return app


async def start_mini_app_server() -> None:
    global _runner, _site
    if _runner is not None:
        return

    enabled = get_mini_app_enabled()
    public_url = get_mini_app_public_url()
    if not enabled and not public_url:
        logger.info("Mini app server disabled: enabled=False and public_url is empty.")
        return
    if not _WEBAPP_DIR.exists():
        logger.warning("Mini app directory not found: %s", _WEBAPP_DIR)
        return

    host = get_mini_app_bind_host()
    port = get_mini_app_bind_port()
    app = _app()
    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host=host, port=port)
    try:
        await _site.start()
        logger.info(
            "Mini app server started on %s:%s (enabled=%s, public_url=%s)",
            host,
            port,
            enabled,
            public_url or "<empty>",
        )
    except Exception:
        await _runner.cleanup()
        _runner = None
        _site = None
        raise


async def stop_mini_app_server() -> None:
    global _runner, _site
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
    _site = None
    _runner = None
    _sessions.clear()
