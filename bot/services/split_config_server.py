import logging
from typing import Optional

from aiohttp import web

from database.requests import (
    get_key_by_split_token,
    list_key_exclusions,
)
from bot.services.split_config_settings import (
    get_split_config_bind_host,
    get_split_config_bind_port,
    get_split_config_enabled,
)
from bot.services.vpn_api import get_client
from bot.utils.key_generator import apply_exclusions_to_json, generate_json

logger = logging.getLogger(__name__)

_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None


async def _split_config_handler(request: web.Request) -> web.Response:
    token = request.match_info.get("token", "").strip()
    if not token:
        return web.json_response({"error": "invalid token"}, status=400)

    key = get_key_by_split_token(token)
    if not key:
        return web.json_response({"error": "not found"}, status=404)

    if not key.get("server_id") or not key.get("panel_email") or not key.get("server_active"):
        return web.json_response({"error": "key not ready"}, status=409)

    try:
        client = await get_client(int(key["server_id"]))
        cfg = await client.get_client_config(str(key["panel_email"]))
        if not cfg:
            return web.json_response({"error": "config unavailable"}, status=502)
        base_json = generate_json(cfg)
        exclusions = list_key_exclusions(int(key["id"]))
        final_json = apply_exclusions_to_json(base_json, exclusions)
        return web.Response(
            text=final_json,
            status=200,
            content_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as e:
        logger.error("Split-config endpoint error: %s", e)
        return web.json_response({"error": "internal error"}, status=500)


async def start_split_config_server() -> None:
    global _runner, _site

    if _runner is not None:
        return

    enabled = get_split_config_enabled()
    if not enabled:
        logger.info("Split-config server disabled by settings.")
        return

    host = get_split_config_bind_host() or "0.0.0.0"
    port = get_split_config_bind_port()

    app = web.Application()
    app.add_routes([web.get("/split/{token}", _split_config_handler)])
    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host=host, port=port)
    try:
        await _site.start()
        logger.info("Split-config server started on %s:%s", host, port)
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
