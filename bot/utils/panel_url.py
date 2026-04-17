"""
Helpers for parsing panel URLs entered in admin flows.
"""

from __future__ import annotations

from urllib.parse import urlparse


def parse_panel_url(raw_value: str) -> dict:
    """
    Parse admin-entered panel URL into protocol/host/port/path.

    Rules:
    - If scheme is omitted and port is 80 -> assume http.
    - If scheme is omitted otherwise -> assume https.
    - Path is normalized to leading + trailing slash (or "/").
    """
    value = (raw_value or "").strip()
    if not value:
        raise ValueError("empty panel url")

    has_scheme = value.startswith(("http://", "https://"))
    probe_value = value if has_scheme else f"//{value}"
    parsed = urlparse(probe_value)

    host = parsed.hostname
    if not host:
        raise ValueError("host is missing")

    port = parsed.port
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if not path.endswith("/"):
        path += "/"

    if has_scheme:
        protocol = parsed.scheme.lower()
        if protocol not in ("http", "https"):
            raise ValueError("unsupported scheme")
        if port is None:
            port = 443 if protocol == "https" else 80
    else:
        if port == 80:
            protocol = "http"
        else:
            protocol = "https"
            if port is None:
                port = 443

    return {
        "protocol": protocol,
        "host": host,
        "port": port,
        "web_base_path": path,
        "panel_url": f"{protocol}://{host}:{port}{path}",
    }
