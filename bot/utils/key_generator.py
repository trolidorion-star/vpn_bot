"""
Утилиты для генерации ключей доступа (VLESS, VMess, Trojan, Shadowsocks, JSON, QR).
Мультипротокольная поддержка для 3X-UI панели.
"""
import json
import base64
import urllib.parse
import io
import logging
import ipaddress
import re
import qrcode
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# ============================================================================
# УНИВЕРСАЛЬНЫЕ РОУТЕРЫ
# ============================================================================

def generate_link(config: Dict[str, Any]) -> str:
    """
    Генерирует ссылку подключения на основе протокола из конфига.
    Поддерживает: vless, vmess, trojan, shadowsocks.
    """
    protocol = config.get('protocol', 'vless')
    
    generators = {
        'vless': generate_vless_link,
        'vmess': generate_vmess_link,
        'trojan': generate_trojan_link,
        'shadowsocks': generate_shadowsocks_link,
    }
    
    gen = generators.get(protocol, generate_vless_link)
    return gen(config)


def generate_json(config: Dict[str, Any]) -> str:
    """
    Генерирует JSON-конфигурацию для Xray/V2Ray клиентов.
    Поддерживает: vless, vmess, trojan, shadowsocks.
    """
    protocol = config.get('protocol', 'vless')
    
    generators = {
        'vless': generate_vless_json,
        'vmess': generate_vmess_json,
        'trojan': generate_trojan_json,
        'shadowsocks': generate_shadowsocks_json,
    }
    
    gen = generators.get(protocol, generate_vless_json)
    return gen(config)


def apply_exclusions_to_json(base_json: str, exclusions: List[Dict[str, Any]]) -> str:
    """
    Adds split-tunnel exclusions to client JSON.
    Excluded destinations are routed via outboundTag=direct.
    """
    data = json.loads(base_json)
    routing = data.setdefault("routing", {})
    routing.setdefault("domainStrategy", "IPIfNonMatch")
    rules = routing.setdefault("rules", [])

    domains: List[str] = []
    ips: List[str] = []

    for item in exclusions:
        rule_type = (item.get("rule_type") or "").lower()
        value = (item.get("rule_value") or "").strip().lower()
        if not value or rule_type != "domain":
            continue

        value = value.replace("https://", "").replace("http://", "")
        value = value.split("/")[0].strip().strip(".")
        if value.startswith("www."):
            value = value[4:]
        if not value:
            continue

        # Normalize IP / CIDR values.
        try:
            if "/" in value:
                ips.append(str(ipaddress.ip_network(value, strict=False)))
                continue
            ips.append(str(ipaddress.ip_address(value)))
            continue
        except ValueError:
            pass

        # Keep only valid domain-like values.
        if "." not in value:
            continue
        if not re.fullmatch(r"[a-z0-9.-]+", value):
            continue
        if ".." in value:
            continue
        domains.append(f"domain:{value}")

    custom_rules: List[Dict[str, Any]] = []
    if domains:
        custom_rules.append(
            {
                "type": "field",
                "domain": sorted(set(domains)),
                "outboundTag": "direct",
            }
        )
    if ips:
        custom_rules.append(
            {
                "type": "field",
                "ip": sorted(set(ips)),
                "outboundTag": "direct",
            }
        )

    # Keep only valid pre-existing rules to avoid broken legacy entries.
    valid_existing_rules: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if any(
            rule.get(field)
            for field in (
                "domain",
                "ip",
                "port",
                "sourcePort",
                "network",
                "protocol",
                "attrs",
                "source",
                "user",
                "inboundTag",
            )
        ):
            valid_existing_rules.append(rule)

    if not valid_existing_rules:
        valid_existing_rules = [
            {
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "direct",
            }
        ]

    routing["rules"] = custom_rules + valid_existing_rules
    return json.dumps(data, indent=2, ensure_ascii=False)


def _split_exclusions(exclusions: List[Dict[str, Any]]) -> tuple[List[str], List[str]]:
    domains: List[str] = []
    ips: List[str] = []
    for item in exclusions or []:
        if (item.get("rule_type") or "").lower() != "domain":
            continue
        value = (item.get("rule_value") or "").strip().lower()
        if not value:
            continue
        value = value.replace("https://", "").replace("http://", "")
        value = value.split("/")[0].strip().strip(".")
        if value.startswith("www."):
            value = value[4:]
        if not value:
            continue
        try:
            if "/" in value:
                ips.append(str(ipaddress.ip_network(value, strict=False)))
            else:
                ips.append(str(ipaddress.ip_address(value)))
            continue
        except ValueError:
            pass

        if "." not in value:
            continue
        if not re.fullmatch(r"[a-z0-9.-]+", value):
            continue
        if ".." in value:
            continue
        domains.append(value)
    return sorted(set(domains)), sorted(set(ips))


def _to_clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _compact_recursive(value: Any) -> Any:
    if isinstance(value, dict):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            cleaned = _compact_recursive(item)
            if cleaned in (None, "", [], {}):
                continue
            result[key] = cleaned
        return result
    if isinstance(value, list):
        result_list: List[Any] = []
        for item in value:
            if item in (None, "", [], {}):
                continue
            cleaned = _compact_recursive(item)
            if cleaned in (None, "", [], {}):
                continue
            result_list.append(cleaned)
        return result_list
    return value


def _get_first_tagged_outbound(outbounds: List[Dict[str, Any]], tag: str) -> Dict[str, Any]:
    for outbound in outbounds:
        if isinstance(outbound, dict) and outbound.get("tag") == tag:
            return outbound
    return {}


def _sanitize_singbox_config(result: Dict[str, Any]) -> Dict[str, Any]:
    outbounds = result.get("outbounds", []) or []
    if not isinstance(outbounds, list):
        outbounds = []

    # Ensure mandatory proxy tag exists for route.final/rules references.
    proxy = _get_first_tagged_outbound(outbounds, "proxy")
    if not proxy and outbounds:
        first = outbounds[0]
        if isinstance(first, dict):
            first["tag"] = "proxy"
    elif not proxy:
        outbounds.append({"type": "direct", "tag": "proxy"})
    result["outbounds"] = outbounds

    valid_tags = {
        outbound.get("tag")
        for outbound in outbounds
        if isinstance(outbound, dict) and outbound.get("tag")
    }

    # Remove detour to avoid parser issues across mixed client core versions.
    dns = result.get("dns", {}) or {}
    servers = dns.get("servers", []) or []
    if isinstance(servers, list):
        for server in servers:
            if isinstance(server, dict):
                server.pop("detour", None)
    for outbound in outbounds:
        if isinstance(outbound, dict):
            outbound.pop("detour", None)

    route = result.get("route", {}) or {}
    rules = route.get("rules", []) or []
    if isinstance(rules, list):
        for rule in rules:
            if isinstance(rule, dict):
                outbound_tag = rule.get("outbound")
                if outbound_tag and outbound_tag not in valid_tags:
                    # Keep config valid even for stale/generated tag mismatches.
                    rule["outbound"] = "direct" if "direct" in valid_tags else "proxy"
    if route.get("final") not in valid_tags:
        route["final"] = "proxy" if "proxy" in valid_tags else "direct"
    result["route"] = route

    return result


def generate_singbox_split_json(config: Dict[str, Any], exclusions: List[Dict[str, Any]]) -> str:
    """
    Generates sing-box client JSON with split rules (direct for exclusions).
    """
    protocol = (config.get("protocol") or "vless").lower()
    stream = config.get("stream_settings", {}) or {}
    network = stream.get("network", "tcp")
    security = (stream.get("security") or "none").lower()
    host = _to_clean_str(config.get("host"))
    try:
        port = int(config.get("port", 443) or 443)
    except (TypeError, ValueError):
        port = 443
    domains, ips = _split_exclusions(exclusions)

    proxy: Dict[str, Any]
    if protocol == "vmess":
        proxy = {
            "type": "vmess",
            "tag": "proxy",
            "server": host,
            "server_port": port,
            "uuid": _to_clean_str(config.get("uuid")),
            "security": _to_clean_str(config.get("security_method")) or "auto",
        }
    elif protocol == "trojan":
        proxy = {
            "type": "trojan",
            "tag": "proxy",
            "server": host,
            "server_port": port,
            "password": _to_clean_str(config.get("password")) or _to_clean_str(config.get("uuid")),
        }
    elif protocol == "shadowsocks":
        proxy = {
            "type": "shadowsocks",
            "tag": "proxy",
            "server": host,
            "server_port": port,
            "method": _to_clean_str(config.get("method")) or "aes-256-gcm",
            "password": _to_clean_str(config.get("password")),
        }
    else:
        proxy = {
            "type": "vless",
            "tag": "proxy",
            "server": host,
            "server_port": port,
            "uuid": _to_clean_str(config.get("uuid")),
        }
        flow = _to_clean_str(config.get("flow"))
        if flow:
            proxy["flow"] = flow

    # TLS / Reality mapping
    if security in {"tls", "reality"}:
        tls: Dict[str, Any] = {"enabled": True}
        sni = ""
        fp = ""
        if security == "tls":
            tls_settings = stream.get("tlsSettings", {}) or {}
            sni = _to_clean_str(tls_settings.get("serverName"))
            fp = (
                _to_clean_str((tls_settings.get("settings", {}) or {}).get("fingerprint"))
                or _to_clean_str(tls_settings.get("fingerprint"))
            )
        else:
            reality = stream.get("realitySettings", {}) or {}
            reality_fallback = config.get("reality", {}) or {}
            inner = reality.get("settings", {}) or {}
            sni = (
                _to_clean_str(inner.get("serverName"))
                or _to_clean_str(reality.get("serverName"))
                or _to_clean_str((reality.get("serverNames", [None])[0] if reality.get("serverNames") else ""))
                or (_to_clean_str(reality.get("dest")).split(":")[0] if reality.get("dest") else "")
                or _to_clean_str(reality_fallback.get("serverName"))
            )
            fp = (
                _to_clean_str(inner.get("fingerprint"))
                or _to_clean_str(reality.get("fingerprint"))
                or _to_clean_str(reality_fallback.get("fingerprint"))
                or "chrome"
            )
            pbk = (
                _to_clean_str(inner.get("publicKey"))
                or _to_clean_str(reality.get("publicKey"))
                or _to_clean_str(reality_fallback.get("publicKey"))
            )
            short_ids = reality.get("shortIds", []) or []
            fallback_short_ids = reality_fallback.get("shortIds", []) or []
            sid = (
                _to_clean_str(short_ids[0] if short_ids else "")
                or _to_clean_str(reality.get("shortId"))
                or _to_clean_str(fallback_short_ids[0] if fallback_short_ids else "")
                or _to_clean_str(reality_fallback.get("shortId"))
            )
            reality_obj: Dict[str, Any] = {"enabled": True}
            if pbk:
                reality_obj["public_key"] = pbk
            if sid:
                reality_obj["short_id"] = sid
            tls["reality"] = reality_obj
        if sni:
            tls["server_name"] = sni
        if fp:
            tls["utls"] = {"enabled": True, "fingerprint": fp}
        proxy["tls"] = tls

    # Transport mapping
    transport: Dict[str, Any] = {}
    if network == "ws":
        ws = stream.get("wsSettings", {}) or {}
        headers = ws.get("headers", {}) or {}
        host_header = _to_clean_str(headers.get("Host")) or _to_clean_str(headers.get("host")) or _to_clean_str(ws.get("host"))
        transport = {"type": "ws", "path": _to_clean_str(ws.get("path")) or "/"}
        if host_header:
            transport["headers"] = {"Host": host_header}
    elif network == "grpc":
        grpc = stream.get("grpcSettings", {}) or {}
        service_name = _to_clean_str(grpc.get("serviceName"))
        if service_name:
            transport = {"type": "grpc", "service_name": service_name}
            authority = _to_clean_str(grpc.get("authority"))
            if authority:
                transport["authority"] = authority
    # Unsupported/rare transport modes are skipped to keep config valid.
    if transport:
        proxy["transport"] = transport

    route_rules: List[Dict[str, Any]] = []
    dns_rules: List[Dict[str, Any]] = []
    if domains:
        route_rules.append({"domain_suffix": domains, "outbound": "direct"})
        dns_rules.append({"domain_suffix": domains, "server": "dns-local"})
    if ips:
        route_rules.append({"ip_cidr": ips, "outbound": "direct"})
    route_rules.append({"ip_is_private": True, "outbound": "direct"})

    result = {
        "log": {"level": "warn"},
        "dns": {
            "servers": [
                {"tag": "dns-remote", "address": "https://1.1.1.1/dns-query"},
                {"tag": "dns-local", "address": "local"},
            ],
            "rules": dns_rules,
            "final": "dns-remote",
            "strategy": "prefer_ipv4",
        },
        "outbounds": [
            proxy,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "auto_detect_interface": True,
            "rules": route_rules,
            "final": "proxy",
        },
    }
    sanitized = _sanitize_singbox_config(result)
    return json.dumps(_compact_recursive(sanitized), indent=2, ensure_ascii=False)


# ============================================================================
# ОБЩИЕ УТИЛИТЫ
# ============================================================================

def _get_remark(config: Dict[str, Any]) -> str:
    """Формирует имя подключения (remark)."""
    remark_part = config.get('inbound_name', 'VPN')
    email_part = config.get('email', '')
    return f"{remark_part}-{email_part}"


def _parse_transport_params(stream: dict, params: dict) -> None:
    """Извлекает параметры транспорта из stream_settings и добавляет в params."""
    network = stream.get('network', 'tcp')
    
    if network == 'tcp':
        tcp_settings = stream.get('tcpSettings', {})
        header = tcp_settings.get('header', {})
        if header.get('type') == 'http':
            params['headerType'] = 'http'
            request = header.get('request', {})
            request_path = request.get('path', [])
            if request_path:
                params['path'] = request_path[0]
            headers = request.get('headers', {})
            host = _search_host(headers)
            if host:
                params['host'] = host
    
    elif network == 'kcp':
        kcp_settings = stream.get('kcpSettings', {})
        header = kcp_settings.get('header', {})
        params['headerType'] = header.get('type', 'none')
        seed = kcp_settings.get('seed', '')
        if seed:
            params['seed'] = seed
    
    elif network == 'ws':
        ws_settings = stream.get('wsSettings', {})
        params['path'] = ws_settings.get('path', '/')
        host = ws_settings.get('host', '')
        if not host:
            headers = ws_settings.get('headers', {})
            host = _search_host(headers)
        if host:
            params['host'] = host
    
    elif network == 'grpc':
        grpc_settings = stream.get('grpcSettings', {})
        params['serviceName'] = grpc_settings.get('serviceName', '')
        authority = grpc_settings.get('authority', '')
        if authority:
            params['authority'] = authority
        if grpc_settings.get('multiMode'):
            params['mode'] = 'multi'
    
    elif network == 'httpupgrade':
        hu_settings = stream.get('httpupgradeSettings', {})
        params['path'] = hu_settings.get('path', '/')
        host = hu_settings.get('host', '')
        if not host:
            headers = hu_settings.get('headers', {})
            host = _search_host(headers)
        if host:
            params['host'] = host
    
    elif network == 'xhttp':
        xhttp_settings = stream.get('xhttpSettings', {})
        params['path'] = xhttp_settings.get('path', '/')
        host = xhttp_settings.get('host', '')
        if not host:
            headers = xhttp_settings.get('headers', {})
            host = _search_host(headers)
        if host:
            params['host'] = host
        params['mode'] = xhttp_settings.get('mode', 'auto')


def _parse_security_params(stream: dict, params: dict) -> None:
    """Извлекает параметры безопасности (TLS/Reality) из stream_settings."""
    security = stream.get('security', 'none')
    
    if security == 'tls':
        params['security'] = 'tls'
        tls_settings = stream.get('tlsSettings', {})
        
        if tls_settings.get('serverName'):
            params['sni'] = tls_settings['serverName']
        
        settings = tls_settings.get('settings', {})
        fp = settings.get('fingerprint', '') or tls_settings.get('fingerprint', '')
        if fp:
            params['fp'] = fp
        
        alpns = tls_settings.get('alpn', [])
        if alpns:
            params['alpn'] = ','.join(alpns)
    
    elif security == 'reality':
        params['security'] = 'reality'
        reality_settings = stream.get('realitySettings', {})
        settings_inner = reality_settings.get('settings', {})
        
        # SNI
        sni = settings_inner.get('serverName', '')
        if not sni:
            sni = reality_settings.get('serverName', '')
        if not sni:
            server_names = reality_settings.get('serverNames', [])
            if server_names:
                sni = server_names[0]
        if not sni:
            sni = reality_settings.get('dest', '').split(':')[0]
        if sni:
            params['sni'] = sni
        
        # Fingerprint
        fp = settings_inner.get('fingerprint', '') or reality_settings.get('fingerprint', '') or 'chrome'
        params['fp'] = fp
        
        # Public Key
        pbk = settings_inner.get('publicKey', '') or reality_settings.get('publicKey', '')
        if pbk:
            params['pbk'] = pbk
        
        # Short ID
        short_ids = reality_settings.get('shortIds', [])
        sid = short_ids[0] if short_ids else ''
        if not sid:
            sid = reality_settings.get('shortId', '')
        if sid:
            params['sid'] = sid
        
        # Spider X
        spx = settings_inner.get('spiderX', '') or reality_settings.get('spiderX', '') or '/'
        if spx:
            params['spx'] = spx
    
    else:
        params['security'] = 'none'


def _search_host(headers: dict) -> str:
    """Ищет значение Host в заголовках (может быть строкой или списком)."""
    if not headers:
        return ''
    host = headers.get('Host', headers.get('host', ''))
    if isinstance(host, list):
        return host[0] if host else ''
    return host


# ============================================================================
# VLESS
# ============================================================================

def generate_vless_link(config: Dict[str, Any]) -> str:
    """Генерирует ссылку vless:// из конфигурации."""
    uuid = config['uuid']
    host = config['host']
    port = config['port']
    name = urllib.parse.quote(_get_remark(config), safe='')
    
    stream = config.get('stream_settings', {})
    network = stream.get('network', 'tcp')
    
    # Порядок параметров как у 3X-UI панели
    params = {
        "type": network,
        "encryption": "none",  # Обязательный параметр для VLESS
    }
    
    _parse_transport_params(stream, params)
    _parse_security_params(stream, params)
    
    # Flow (для VLESS TCP + Reality/TLS)
    flow = config.get('flow', '')
    if flow:
        params['flow'] = flow
    
    # safe='' чтобы / кодировался как %2F (как у панели)
    query = "&".join([f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items() if v])
    link = f"vless://{uuid}@{host}:{port}?{query}#{name}"
    logger.info(f"Generated VLESS link params: security={params.get('security')}, sni={params.get('sni')}, pbk={params.get('pbk','')[:16]}..., flow={params.get('flow')}, fp={params.get('fp')}")
    return link


def generate_vless_json(config: Dict[str, Any]) -> str:
    """Генерирует JSON-конфигурацию для VLESS."""
    stream = config.get('stream_settings', {})
    network = stream.get('network', 'tcp')
    security = stream.get('security', 'none')
    flow = config.get('flow', '')
    user = {
        "id": config['uuid'],
        "encryption": "none",
    }
    if flow:
        user["flow"] = flow

    outbound = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": config['host'],
                "port": config['port'],
                "users": [user]
            }]
        },
        "streamSettings": _build_stream_settings(stream),
        "tag": "proxy"
    }
    
    return _wrap_outbound(outbound)


# ============================================================================
# VMESS
# ============================================================================

def generate_vmess_link(config: Dict[str, Any]) -> str:
    """Генерирует ссылку vmess:// из конфигурации (base64 JSON)."""
    stream = config.get('stream_settings', {})
    network = stream.get('network', 'tcp')
    security = stream.get('security', 'none')
    name = _get_remark(config)
    
    obj = {
        "v": "2",
        "ps": name,
        "add": config['host'],
        "port": config['port'],
        "id": config['uuid'],
        "scy": config.get('security_method', 'auto'),
        "net": network,
        "type": "none",
    }
    
    # Транспорт
    if network == 'tcp':
        tcp = stream.get('tcpSettings', {})
        header = tcp.get('header', {})
        obj['type'] = header.get('type', 'none')
        if obj['type'] == 'http':
            request = header.get('request', {})
            request_path = request.get('path', ['/'])
            obj['path'] = request_path[0] if request_path else '/'
            headers = request.get('headers', {})
            obj['host'] = _search_host(headers)
    elif network == 'ws':
        ws = stream.get('wsSettings', {})
        obj['path'] = ws.get('path', '/')
        host = ws.get('host', '')
        if not host:
            headers = ws.get('headers', {})
            host = _search_host(headers)
        obj['host'] = host
    elif network == 'grpc':
        grpc = stream.get('grpcSettings', {})
        obj['path'] = grpc.get('serviceName', '')
        obj['authority'] = grpc.get('authority', '')
        if grpc.get('multiMode'):
            obj['type'] = 'multi'
    elif network == 'kcp':
        kcp = stream.get('kcpSettings', {})
        header = kcp.get('header', {})
        obj['type'] = header.get('type', 'none')
        obj['path'] = kcp.get('seed', '')
    elif network == 'httpupgrade':
        hu = stream.get('httpupgradeSettings', {})
        obj['path'] = hu.get('path', '/')
        host = hu.get('host', '')
        if not host:
            headers = hu.get('headers', {})
            host = _search_host(headers)
        obj['host'] = host
    elif network == 'xhttp':
        xhttp = stream.get('xhttpSettings', {})
        obj['path'] = xhttp.get('path', '/')
        host = xhttp.get('host', '')
        if not host:
            headers = xhttp.get('headers', {})
            host = _search_host(headers)
        obj['host'] = host
        obj['mode'] = xhttp.get('mode', 'auto')
    
    # Безопасность
    obj['tls'] = security
    if security == 'tls':
        tls_settings = stream.get('tlsSettings', {})
        alpns = tls_settings.get('alpn', [])
        if alpns:
            obj['alpn'] = ','.join(alpns)
        if tls_settings.get('serverName'):
            obj['sni'] = tls_settings['serverName']
        settings = tls_settings.get('settings', {})
        if settings.get('fingerprint'):
            obj['fp'] = settings['fingerprint']
    
    json_str = json.dumps(obj, indent=2, ensure_ascii=False)
    return "vmess://" + base64.b64encode(json_str.encode()).decode()


def generate_vmess_json(config: Dict[str, Any]) -> str:
    """Генерирует JSON-конфигурацию для VMess."""
    stream = config.get('stream_settings', {})
    
    outbound = {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": config['host'],
                "port": config['port'],
                "users": [{
                    "id": config['uuid'],
                    "security": config.get('security_method', 'auto'),
                    "alterId": 0
                }]
            }]
        },
        "streamSettings": _build_stream_settings(stream),
        "tag": "proxy"
    }
    
    return _wrap_outbound(outbound)


# ============================================================================
# TROJAN
# ============================================================================

def generate_trojan_link(config: Dict[str, Any]) -> str:
    """Генерирует ссылку trojan:// из конфигурации."""
    password = config.get('password', config.get('uuid', ''))
    host = config['host']
    port = config['port']
    name = urllib.parse.quote(_get_remark(config), safe='')
    
    stream = config.get('stream_settings', {})
    network = stream.get('network', 'tcp')
    
    params = {"type": network}
    
    _parse_transport_params(stream, params)
    _parse_security_params(stream, params)
    
    # safe='' чтобы / кодировался как %2F (как у панели 3X-UI)
    query = "&".join([f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items() if v])
    return f"trojan://{password}@{host}:{port}?{query}#{name}"


def generate_trojan_json(config: Dict[str, Any]) -> str:
    """Генерирует JSON-конфигурацию для Trojan."""
    stream = config.get('stream_settings', {})
    password = config.get('password', config.get('uuid', ''))
    
    outbound = {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": config['host'],
                "port": config['port'],
                "password": password
            }]
        },
        "streamSettings": _build_stream_settings(stream),
        "tag": "proxy"
    }
    
    return _wrap_outbound(outbound)


# ============================================================================
# SHADOWSOCKS
# ============================================================================

def generate_shadowsocks_link(config: Dict[str, Any]) -> str:
    """Генерирует ссылку ss:// из конфигурации."""
    method = config.get('method', 'aes-256-gcm')
    password = config.get('password', '')
    server_password = config.get('server_password', '')
    host = config['host']
    port = config['port']
    name = urllib.parse.quote(_get_remark(config))
    
    # Для Shadowsocks 2022 в режиме Multi-User пароль формируется как ServerPassword:ClientPassword
    if method.startswith('2022-') and server_password and server_password != password:
        password = f"{server_password}:{password}"
    
    # Формат: ss://base64(method:password)@host:port
    user_info = base64.urlsafe_b64encode(f"{method}:{password}".encode()).decode().rstrip('=')
    
    # Добавляем параметры транспорта (как делает 3x-ui: ?type=tcp)
    stream = config.get('stream_settings', {})
    network = stream.get('network', 'tcp')
    
    params = {"type": network}
    _parse_transport_params(stream, params)
    _parse_security_params(stream, params)
    
    # Исключаем security=none чтобы не мусорить, если это дефолт для SS
    if params.get('security') == 'none':
        del params['security']
        
    query = "&".join([f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items() if v])
    
    if query:
        return f"ss://{user_info}@{host}:{port}?{query}#{name}"
    else:
        return f"ss://{user_info}@{host}:{port}#{name}"


def generate_shadowsocks_json(config: Dict[str, Any]) -> str:
    """Генерирует JSON-конфигурацию для Shadowsocks."""
    stream = config.get('stream_settings', {})
    
    outbound = {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": config['host'],
                "port": config['port'],
                "method": config.get('method', 'aes-256-gcm'),
                "password": f"{config['server_password']}:{config['password']}" if config.get('server_password') and config.get('method', '').startswith('2022-') and config['server_password'] != config['password'] else config.get('password', ''),
            }]
        },
        "streamSettings": _build_stream_settings(stream),
        "tag": "proxy"
    }
    
    return _wrap_outbound(outbound)


# ============================================================================
# ОБЩИЕ ХЕЛПЕРЫ ДЛЯ JSON
# ============================================================================

def _build_stream_settings_legacy(stream: dict) -> dict:
    """Строит объект streamSettings для JSON-конфига."""
    network = stream.get('network', 'tcp')
    security = stream.get('security', 'none')
    
    result = {
        "network": network,
        "security": security
    }
    
    # Транспорт
    transport_map = {
        'tcp': 'tcpSettings',
        'kcp': 'kcpSettings',
        'ws': 'wsSettings',
        'grpc': 'grpcSettings',
        'httpupgrade': 'httpupgradeSettings',
        'xhttp': 'xhttpSettings',
    }
    key = transport_map.get(network)
    if key and key in stream:
        result[key] = stream[key]
    
    # Безопасность
    if security == 'tls' and 'tlsSettings' in stream:
        result['tlsSettings'] = stream['tlsSettings']
    elif security == 'reality' and 'realitySettings' in stream:
        result['realitySettings'] = stream['realitySettings']
    
    return result


def _compact_dict(data: dict) -> dict:
    return {k: v for k, v in data.items() if v not in ("", None, [], {})}


def _first_non_empty(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _build_stream_settings(stream: dict) -> dict:
    """РЎС‚СЂРѕРёС‚ outbound streamSettings РґР»СЏ Xray-РєР»РёРµРЅС‚Р° РёР· inbound РјРѕРґРµР»Рё 3x-ui."""
    network = (stream.get("network") or "tcp").lower()
    security = (stream.get("security") or "none").lower()

    result = {
        "network": network,
        "security": security,
    }

    if network == "ws":
        ws = stream.get("wsSettings", {}) or {}
        headers = ws.get("headers", {}) or {}
        host = _first_non_empty(ws.get("host"), headers.get("Host"), headers.get("host"))
        result["wsSettings"] = _compact_dict(
            {
                "path": ws.get("path") or "/",
                "headers": {"Host": host} if host else {},
            }
        )
    elif network == "grpc":
        grpc = stream.get("grpcSettings", {}) or {}
        result["grpcSettings"] = _compact_dict(
            {
                "serviceName": grpc.get("serviceName"),
                "authority": grpc.get("authority"),
                "multiMode": grpc.get("multiMode") if isinstance(grpc.get("multiMode"), bool) else None,
            }
        )
    elif network == "tcp":
        tcp = stream.get("tcpSettings", {}) or {}
        header = tcp.get("header", {}) or {}
        header_type = (header.get("type") or "none").strip()
        if header_type and header_type != "none":
            result["tcpSettings"] = {"header": _compact_dict({"type": header_type})}
    elif network == "kcp":
        kcp = stream.get("kcpSettings", {}) or {}
        header = kcp.get("header", {}) or {}
        result["kcpSettings"] = _compact_dict(
            {
                "mtu": kcp.get("mtu"),
                "tti": kcp.get("tti"),
                "uplinkCapacity": kcp.get("uplinkCapacity"),
                "downlinkCapacity": kcp.get("downlinkCapacity"),
                "congestion": kcp.get("congestion") if isinstance(kcp.get("congestion"), bool) else None,
                "readBufferSize": kcp.get("readBufferSize"),
                "writeBufferSize": kcp.get("writeBufferSize"),
                "seed": kcp.get("seed"),
                "header": _compact_dict({"type": header.get("type") or "none"}),
            }
        )
    elif network == "httpupgrade":
        hu = stream.get("httpupgradeSettings", {}) or {}
        headers = hu.get("headers", {}) or {}
        host = _first_non_empty(hu.get("host"), headers.get("Host"), headers.get("host"))
        result["httpupgradeSettings"] = _compact_dict(
            {
                "path": hu.get("path") or "/",
                "host": host,
            }
        )
    elif network == "xhttp":
        xhttp = stream.get("xhttpSettings", {}) or {}
        headers = xhttp.get("headers", {}) or {}
        host = _first_non_empty(xhttp.get("host"), headers.get("Host"), headers.get("host"))
        result["xhttpSettings"] = _compact_dict(
            {
                "path": xhttp.get("path") or "/",
                "host": host,
                "mode": xhttp.get("mode"),
            }
        )

    if security == "tls":
        tls_settings = stream.get("tlsSettings", {}) or {}
        inner = tls_settings.get("settings", {}) or {}
        alpn = tls_settings.get("alpn")
        if isinstance(alpn, str):
            alpn = [x.strip() for x in alpn.split(",") if x.strip()]
        result["tlsSettings"] = _compact_dict(
            {
                "serverName": tls_settings.get("serverName"),
                "fingerprint": _first_non_empty(inner.get("fingerprint"), tls_settings.get("fingerprint")),
                "alpn": alpn if isinstance(alpn, list) else None,
                "allowInsecure": tls_settings.get("allowInsecure") if isinstance(tls_settings.get("allowInsecure"), bool) else None,
            }
        )
    elif security == "reality":
        reality = stream.get("realitySettings", {}) or {}
        inner = reality.get("settings", {}) or {}
        short_ids = reality.get("shortIds", []) or []
        short_id = _first_non_empty(short_ids[0] if short_ids else "", reality.get("shortId"))
        result["realitySettings"] = _compact_dict(
            {
                "show": False,
                "fingerprint": _first_non_empty(inner.get("fingerprint"), reality.get("fingerprint"), "chrome"),
                "serverName": _first_non_empty(
                    inner.get("serverName"),
                    reality.get("serverName"),
                    (reality.get("serverNames") or [None])[0],
                    (str(reality.get("dest", "")).split(":")[0] if reality.get("dest") else ""),
                ),
                "publicKey": _first_non_empty(inner.get("publicKey"), reality.get("publicKey")),
                "shortId": short_id,
                "spiderX": _first_non_empty(inner.get("spiderX"), reality.get("spiderX"), "/"),
            }
        )

    return _compact_dict(result)


def _wrap_outbound(outbound: dict) -> str:
    """Оборачивает outbound в полный клиентский конфиг Xray."""
    final_config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 1080,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True}
        }],
        "outbounds": [
            outbound,
            {"protocol": "freedom", "tag": "direct"}
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [{
                "type": "field",
                "ip": ["geoip:private"],
                "outboundTag": "direct"
            }]
        }
    }
    return json.dumps(final_config, indent=2, ensure_ascii=False)


# ============================================================================
# QR-КОД
# ============================================================================

def generate_qr_code(data: str) -> bytes:
    """
    Генерирует QR-код из строки.
    
    Args:
        data: Данные для QR-кода
        
    Returns:
        Байты изображения (PNG)
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    
    return img_byte_arr.getvalue()
