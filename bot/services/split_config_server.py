import asyncio
import copy
import json
import logging
import os
import threading
from typing import Any, Optional

import config as app_config
from aiohttp import web

from bot.services.split_config_settings import (
    get_split_config_bind_port,
    get_split_config_enabled,
    get_split_config_public_base_url,
)
from bot.services.vpn_api import get_isolated_client
from bot.utils.key_generator import (
    apply_exclusions_to_json,
    generate_json,
    generate_singbox_split_json,
)
from database.requests import get_key_by_split_token, list_key_exclusions

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None
_server_loop: Optional[asyncio.AbstractEventLoop] = None
_server_thread: Optional[threading.Thread] = None
_startup_done = threading.Event()
_shutdown_done = threading.Event()
_state_lock = threading.Lock()
_server_ready = False
_server_error: Optional[BaseException] = None


def _cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _from_config_or_env(attr_names: tuple[str, ...], env_names: tuple[str, ...], default: str = "") -> str:
    for name in attr_names:
        if hasattr(app_config, name):
            value = _first_non_empty(getattr(app_config, name))
            if value:
                return value

    for name in env_names:
        value = _first_non_empty(os.getenv(name))
        if value:
            return value

    return default


def _get_reality_fallback_sni() -> str:
    return _from_config_or_env(
        (
            "SPLIT_CONFIG_REALITY_FALLBACK_SNI",
            "REALITY_FALLBACK_SNI",
            "DEFAULT_REALITY_SNI",
            "XRAY_REALITY_FALLBACK_SNI",
        ),
        (
            "SPLIT_CONFIG_REALITY_FALLBACK_SNI",
            "REALITY_FALLBACK_SNI",
            "DEFAULT_REALITY_SNI",
            "XRAY_REALITY_FALLBACK_SNI",
        ),
        default="www.microsoft.com",
    )


def _get_reality_fallback_public_key() -> str:
    return _from_config_or_env(
        (
            "SPLIT_CONFIG_REALITY_FALLBACK_PUBLIC_KEY",
            "REALITY_FALLBACK_PUBLIC_KEY",
            "DEFAULT_REALITY_PUBLIC_KEY",
            "XRAY_REALITY_FALLBACK_PUBLIC_KEY",
        ),
        (
            "SPLIT_CONFIG_REALITY_FALLBACK_PUBLIC_KEY",
            "REALITY_FALLBACK_PUBLIC_KEY",
            "DEFAULT_REALITY_PUBLIC_KEY",
            "XRAY_REALITY_FALLBACK_PUBLIC_KEY",
        ),
        default="PLEASE_SET_REALITY_PUBLIC_KEY",
    )


def _prepare_reality_config(raw_cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(raw_cfg or {})
    stream = cfg.get("stream_settings")
    if not isinstance(stream, dict):
        return cfg

    security = (stream.get("security") or "").lower()
    if security != "reality":
        return cfg

    reality = stream.get("realitySettings")
    if not isinstance(reality, dict):
        reality = {}

    inner = reality.get("settings")
    if not isinstance(inner, dict):
        inner = {}

    sni = _first_non_empty(
        inner.get("serverName"),
        reality.get("serverName"),
        ((reality.get("serverNames") or [""])[0] if isinstance(reality.get("serverNames"), list) else ""),
        (str(reality.get("dest", "")).split(":")[0] if reality.get("dest") else ""),
    )
    if not sni:
        sni = _get_reality_fallback_sni()
        logger.warning("Reality serverName missing in panel config, using fallback SNI: %s", sni)

    public_key = _first_non_empty(
        inner.get("publicKey"),
        reality.get("publicKey"),
        cfg.get("publicKey"),
        cfg.get("pbk"),
    )
    if not public_key:
        public_key = _get_reality_fallback_public_key()
        logger.warning("Reality publicKey missing in panel config, using fallback publicKey.")

    if sni:
        inner["serverName"] = sni
        reality["serverName"] = sni
        server_names = reality.get("serverNames")
        if not isinstance(server_names, list) or not any(_first_non_empty(x) for x in server_names):
            reality["serverNames"] = [sni]

    if public_key:
        inner["publicKey"] = public_key
        reality["publicKey"] = public_key

    reality["settings"] = inner
    stream["realitySettings"] = reality
    cfg["stream_settings"] = stream
    return cfg


async def _split_config_handler(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "").strip()
    if token.endswith(".json"):
        token = token[:-5]
    logger.info("Request for token %s from IP %s", token or "<empty>", request.remote or "<unknown>")
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
        client = await get_isolated_client(int(key["server_id"]))
        try:
            cfg = await client.get_client_config(str(key["panel_email"]))
        finally:
            try:
                await client.close()
            except Exception:
                logger.exception("CRITICAL ERROR: failed to close isolated panel client")
        if not cfg:
            return web.json_response({"error": "config unavailable"}, status=502, headers=_cache_headers())

        cfg = _prepare_reality_config(cfg)

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
            base_json = generate_json(cfg)
            final_json = apply_exclusions_to_json(base_json, exclusions)
        try:
            parsed = json.loads(final_json)
            if isinstance(parsed, dict) and parsed.get("error"):
                raise web.HTTPInternalServerError(reason=str(parsed["error"]))
        except json.JSONDecodeError:
            pass

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
    except web.HTTPException as http_exc:
        logger.exception("Split-config HTTP error for token %s", token)
        return web.json_response(
            {"error": http_exc.reason or "internal error"},
            status=500,
            headers=_cache_headers(),
        )
    except Exception:
        logger.exception("Split-config endpoint error")
        return web.json_response({"error": "internal error"}, status=500, headers=_cache_headers())


async def _health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"}, headers=_cache_headers())


async def _create_server(host: str, port: int) -> None:
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


async def _cleanup_server() -> None:
    global _runner, _site

    if _site is not None:
        try:
            await _site.stop()
        except Exception:
            logger.exception("CRITICAL ERROR: failed to stop split-config site")

    if _runner is not None:
        try:
            await _runner.cleanup()
        except Exception:
            logger.exception("CRITICAL ERROR: failed to cleanup split-config runner")

    _site = None
    _runner = None


def _server_thread_main(host: str, port: int, enabled: bool, public_base: str) -> None:
    global _server_loop, _server_error, _server_ready, _server_thread

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    with _state_lock:
        _server_loop = loop

    try:
        loop.run_until_complete(_create_server(host, port))
        with _state_lock:
            _server_ready = True
        _startup_done.set()

        logger.info(
            "Split-config server started on %s:%s (enabled=%s, public_base=%s)",
            host,
            port,
            enabled,
            public_base or "<empty>",
        )

        loop.run_forever()
    except Exception as exc:
        with _state_lock:
            _server_error = exc
            _server_ready = False
        _startup_done.set()
        logger.exception(
            "CRITICAL ERROR: split-config server thread crashed (host=%s port=%s)",
            host,
            port,
        )
    finally:
        try:
            loop.run_until_complete(_cleanup_server())
        except Exception:
            logger.exception("CRITICAL ERROR: split-config server cleanup crashed")

        try:
            loop.close()
        except Exception:
            logger.exception("CRITICAL ERROR: failed to close split-config event loop")

        with _state_lock:
            _server_loop = None
            _server_ready = False
            _server_thread = None

        _shutdown_done.set()


async def start_split_config_server(startup_timeout: float = 10.0) -> None:
    global _server_thread, _server_error, _server_ready

    enabled = get_split_config_enabled()
    public_base = get_split_config_public_base_url()
    if not enabled and not public_base:
        logger.info("Split-config server disabled: enabled=False and public_base_url is empty.")
        return

    host = "0.0.0.0"
    port = get_split_config_bind_port()

    with _state_lock:
        if _server_thread is not None and _server_thread.is_alive() and _server_ready:
            return

        _server_error = None
        _server_ready = False
        _startup_done.clear()
        _shutdown_done.clear()

        thread = threading.Thread(
            target=_server_thread_main,
            args=(host, port, enabled, public_base),
            name="split-config-server",
            daemon=True,
        )
        _server_thread = thread

    thread.start()

    started = await asyncio.to_thread(_startup_done.wait, startup_timeout)
    if not started:
        await stop_split_config_server(join_timeout=2.0)
        raise TimeoutError(f"Split-config server startup timed out after {startup_timeout:.1f}s")

    with _state_lock:
        error = _server_error
        ready = _server_ready

    if error is not None:
        raise RuntimeError(f"Split-config server failed to start on {host}:{port}") from error

    if not ready:
        raise RuntimeError("Split-config server did not reach ready state")


async def stop_split_config_server(join_timeout: float = 5.0) -> None:
    with _state_lock:
        thread = _server_thread
        loop = _server_loop

    if thread is None:
        return

    if loop is not None and loop.is_running():
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            logger.exception("CRITICAL ERROR: failed to signal split-config loop stop")

    await asyncio.to_thread(thread.join, join_timeout)

    if thread.is_alive():
        logger.error("Split-config server thread did not stop within %.1f seconds", join_timeout)
