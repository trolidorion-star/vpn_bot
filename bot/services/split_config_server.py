import logging
from typing import Optional

from aiohttp import web

from bot.services.split_config_settings import (
    get_split_config_bind_host,
    get_split_config_bind_port,
    get_split_config_enabled,
    get_split_config_public_base_url,
)
from bot.services.vpn_api import get_client
from bot.utils.key_generator import (
    apply_exclusions_to_json,
    generate_json,
    generate_singbox_split_json,
)
from database.requests import (
    get_key_by_split_token,
    list_key_exclusions,
)

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None


def _cache_headers() -> dict:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }


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
        client = await get_client(int(key["server_id"]))
        cfg = await client.get_client_config(str(key["panel_email"]))
        if not cfg:
            return web.json_response({"error": "config unavailable"}, status=502, headers=_cache_headers())

        exclusions = list_key_exclusions(int(key["id"]))
        # Smart-link default is sing-box format for modern clients with split routing.
        fmt = (request.query.get("format") or "singbox").strip().lower()
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


async def start_split_config_server() -> None:
    global _runner, _site

    if _runner is not None:
        return

    enabled = get_split_config_enabled()
    public_base = get_split_config_public_base_url()
    if not enabled and not public_base:
        logger.info("Split-config server disabled: enabled=False and public_base_url is empty.")
        return

    host = get_split_config_bind_host() or "0.0.0.0"
    port = get_split_config_bind_port()

    app = web.Application()
    app.add_routes(
        [
            web.get("/split/{token}", _split_config_handler),
            web.get("/split/{token}.json", _split_config_handler),
            web.get("/sub/{token}", _split_config_handler),
            web.get("/sub/{token}.json", _split_config_handler),
            web.get("/split/health", _health_handler),
        ]
    )

    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host=host, port=port)
    try:
        await _site.start()
        logger.info(
            "Split-config server started on %s:%s (enabled=%s, public_base=%s)",
            host,
            port,
            enabled,
            public_base or "<empty>",
        )
    except Exception:
        await _runner.cleanup()
        _runner = None
        _site = None
        raise


async def stop_split_config_server() -> None:
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
