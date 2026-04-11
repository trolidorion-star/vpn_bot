import logging
import json
import asyncio
import threading
from typing import Optional

from aiohttp import web

from bot.services.split_config_settings import (
    get_split_config_bind_host,
    get_split_config_bind_port,
    get_split_config_enabled,
    get_split_config_public_base_url,
)
from bot.services.panels.xui import XUIClient
from bot.services.panels.marzban import MarzbanClient
from bot.utils.key_generator import (
    generate_singbox_split_json,
    generate_xray_split_json,
)
from database.requests import (
    get_key_by_split_token,
    get_server_by_id,
    list_key_exclusions,
)

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None
_thread: Optional[threading.Thread] = None
_thread_loop: Optional[asyncio.AbstractEventLoop] = None
_start_event = threading.Event()
_start_error: Optional[Exception] = None


def _cache_headers() -> dict:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _extract_proxy_reality_snapshot(config_json: str) -> dict:
    try:
        data = json.loads(config_json)
        outbounds = data.get("outbounds", []) or []
        proxy = next((o for o in outbounds if isinstance(o, dict) and o.get("tag") == "proxy"), None)
        if not proxy:
            return {}
        stream = proxy.get("streamSettings", {}) or {}
        reality = stream.get("realitySettings", {}) or {}
        inner = reality.get("settings", {}) or {}
        vnext = ((proxy.get("settings") or {}).get("vnext") or [{}])[0] or {}
        user = (vnext.get("users") or [{}])[0] or {}
        return {
            "address": vnext.get("address"),
            "port": vnext.get("port"),
            "security": stream.get("security"),
            "network": stream.get("network"),
            "sni": inner.get("serverName") or reality.get("serverName"),
            "pbk": inner.get("publicKey") or reality.get("publicKey"),
            "fp": inner.get("fingerprint") or reality.get("fingerprint"),
            "flow": user.get("flow"),
        }
    except Exception:
        return {}


async def _fetch_client_config(server_id: int, panel_email: str):
    server = get_server_by_id(server_id)
    if not server:
        return None
    panel_type = (server.get("panel_type") or "xui").lower()
    client = MarzbanClient(server) if panel_type == "marzban" else XUIClient(server)
    try:
        return await client.get_client_config(panel_email)
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _split_config_handler(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "").strip()
    if token.endswith(".json"):
        token = token[:-5]
    if not token:
        return web.json_response({"error": "invalid token"}, status=400, headers=_cache_headers())

    key = get_key_by_split_token(token)
    if not key:
        logger.warning("Split-config token not found: %s", token)
        return web.json_response({"error": "not found"}, status=404, headers=_cache_headers())

    if not key.get("server_id") or not key.get("panel_email") or not key.get("server_active"):
        logger.warning("Split-config key not ready: key_id=%s", key.get("id"))
        return web.json_response({"error": "key not ready"}, status=409, headers=_cache_headers())

    try:
        cfg = await _fetch_client_config(int(key["server_id"]), str(key["panel_email"]))
        if not cfg:
            return web.json_response({"error": "config unavailable"}, status=502, headers=_cache_headers())

        exclusions = list_key_exclusions(int(key["id"]))
        fmt = (request.query.get("format") or "xray").strip().lower()
        download = (request.query.get("download") or "").strip().lower() in {"1", "true", "yes"}
        logger.info(
            "Split-config request: key_id=%s format=%s download=%s exclusions=%s",
            key.get("id"),
            fmt,
            download,
            len(exclusions or []),
        )
        if fmt == "singbox":
            final_json = generate_singbox_split_json(cfg, exclusions)
        else:
            final_json = generate_xray_split_json(cfg, exclusions)
            snapshot = _extract_proxy_reality_snapshot(final_json)
            if snapshot:
                logger.info(
                    "Split-config proxy snapshot: addr=%s port=%s sec=%s net=%s sni=%s pbk=%s fp=%s flow=%s",
                    snapshot.get("address"),
                    snapshot.get("port"),
                    snapshot.get("security"),
                    snapshot.get("network"),
                    snapshot.get("sni"),
                    bool(snapshot.get("pbk")),
                    snapshot.get("fp"),
                    snapshot.get("flow"),
                )
                if snapshot.get("security") == "reality" and (not snapshot.get("sni") or not snapshot.get("pbk")):
                    logger.error(
                        "Refusing to serve invalid Reality config: missing sni or publicKey (key_id=%s).",
                        key.get("id"),
                    )
                    return web.json_response(
                        {"error": "invalid reality config: missing sni/publicKey"},
                        status=502,
                        headers=_cache_headers(),
                    )
        headers = {
            **_cache_headers(),
            "X-Split-Config": "1",
        }
        if download:
            headers["Content-Disposition"] = f'attachment; filename="split_{fmt}_{key["id"]}.json"'
        return web.Response(
            text=final_json,
            status=200,
            content_type="application/json",
            charset="utf-8",
            headers=headers,
        )
    except Exception as e:
        logger.error("Split-config endpoint error: %s", e)
        return web.json_response({"error": "internal error"}, status=500, headers=_cache_headers())


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"}, headers=_cache_headers())


async def _async_start_server(host: str, port: int, enabled: bool, public_base: str) -> None:
    global _runner, _site

    app = web.Application()
    app.add_routes(
        [
            web.get("/split/health", _health_handler),
            web.get("/split/{token}", _split_config_handler),
            web.get("/split/{token}.json", _split_config_handler),
            web.get("/sub/{token}", _split_config_handler),
            web.get("/sub/{token}.json", _split_config_handler),
        ]
    )

    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host=host, port=port)
    await _site.start()
    logger.info(
        "Split-config server started on %s:%s (enabled=%s, public_base=%s)",
        host,
        port,
        enabled,
        public_base or "<empty>",
    )


async def _async_stop_server() -> None:
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


def _server_thread_main(host: str, port: int, enabled: bool, public_base: str) -> None:
    global _thread_loop, _start_error
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _thread_loop = loop
    try:
        loop.run_until_complete(_async_start_server(host, port, enabled, public_base))
        _start_event.set()
        loop.run_forever()
    except Exception as e:
        _start_error = e
        logger.exception("Failed to start split-config server on %s:%s: %s", host, port, e)
        _start_event.set()
    finally:
        try:
            loop.run_until_complete(_async_stop_server())
        except Exception:
            pass
        loop.close()
        _thread_loop = None


async def start_split_config_server() -> None:
    global _thread, _start_error

    if _thread is not None and _thread.is_alive():
        return

    enabled = get_split_config_enabled()
    public_base = get_split_config_public_base_url()
    if not enabled and not public_base:
        logger.info("Split-config server disabled: enabled=False and public_base_url is empty.")
        return

    host = get_split_config_bind_host() or "0.0.0.0"
    port = get_split_config_bind_port()
    _start_error = None
    _start_event.clear()
    _thread = threading.Thread(
        target=_server_thread_main,
        args=(host, port, enabled, public_base),
        name="split-config-server",
        daemon=True,
    )
    _thread.start()

    started = await asyncio.to_thread(_start_event.wait, 10)
    if not started:
        raise RuntimeError(f"Split-config server start timeout on {host}:{port}")
    if _start_error is not None:
        err = _start_error
        _start_error = None
        raise RuntimeError(f"Split-config server failed: {err}") from err


async def stop_split_config_server() -> None:
    global _thread
    if _thread_loop is not None:
        try:
            _thread_loop.call_soon_threadsafe(_thread_loop.stop)
        except Exception:
            pass
    if _thread is not None:
        await asyncio.to_thread(_thread.join, 10)
    _thread = None
