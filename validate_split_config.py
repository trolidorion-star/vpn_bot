import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List


EFFECTIVE_RULE_FIELDS = {
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
}


def _fail(msg: str) -> None:
    print(f"[FAIL] {msg}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"[OK] {msg}")


def _warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def fetch_json(url: str, timeout: float) -> tuple[Dict[str, Any], Dict[str, str]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = resp.status
    except urllib.error.HTTPError as e:
        _fail(f"HTTP error: {e.code} {e.reason}")
    except urllib.error.URLError as e:
        _fail(f"URL error: {e.reason}")
    except Exception as e:
        _fail(f"Request failed: {e}")

    if status != 200:
        _fail(f"Unexpected HTTP status: {status}")
    _ok(f"Endpoint responded with HTTP {status}")

    ctype = headers.get("content-type", "")
    if "application/json" not in ctype.lower():
        _warn(f"Unexpected Content-Type: {ctype}")
    else:
        _ok(f"Content-Type is JSON: {ctype}")

    try:
        data = json.loads(body)
    except json.JSONDecodeError as e:
        _fail(f"Invalid JSON: {e}")

    return data, headers


def _has_effective_fields(rule: Dict[str, Any]) -> bool:
    return any(rule.get(field) for field in EFFECTIVE_RULE_FIELDS)


def _validate_rules(rules: List[Dict[str, Any]]) -> None:
    if not isinstance(rules, list) or not rules:
        _fail("routing.rules is empty")
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            _fail(f"routing.rules[{i}] is not an object")
        if not _has_effective_fields(rule):
            _fail(f"routing.rules[{i}] has no effective fields")
    _ok(f"routing.rules validated ({len(rules)} rules)")


def validate_xray_config(data: Dict[str, Any]) -> None:
    if not isinstance(data, dict):
        _fail("Top-level JSON is not an object")

    outbounds = data.get("outbounds")
    if not isinstance(outbounds, list) or len(outbounds) < 3:
        _fail("outbounds must contain at least 3 objects")

    by_tag = {}
    for ob in outbounds:
        if isinstance(ob, dict) and ob.get("tag"):
            by_tag[str(ob["tag"])] = ob

    for required_tag in ("proxy", "direct", "blocked"):
        if required_tag not in by_tag:
            _fail(f"Missing outbound tag: {required_tag}")
    _ok("Outbounds include proxy/direct/blocked")

    proxy = by_tag["proxy"]
    if proxy.get("protocol") != "vless":
        _warn(f"Proxy protocol is not vless: {proxy.get('protocol')}")
    else:
        _ok("Proxy protocol is vless")

    vnext = ((proxy.get("settings") or {}).get("vnext") or [])
    if not vnext or not isinstance(vnext, list):
        _fail("proxy.settings.vnext is missing")
    server = vnext[0]
    if not server.get("address") or not server.get("port"):
        _fail("proxy vnext address/port is missing")
    users = server.get("users") or []
    if not users:
        _fail("proxy vnext users is empty")
    user = users[0]
    if user.get("encryption") != "none":
        _fail("VLESS user encryption must be 'none'")
    flow = user.get("flow")
    if flow and flow != "xtls-rprx-vision":
        _fail(f"Unexpected VLESS flow: {flow}")
    _ok("Proxy vnext/users look valid")

    stream = proxy.get("streamSettings") or {}
    if stream.get("security") == "reality":
        reality = stream.get("realitySettings") or {}
        inner = reality.get("settings") or {}
        pbk = inner.get("publicKey") or reality.get("publicKey")
        sni = inner.get("serverName") or reality.get("serverName")
        fp = inner.get("fingerprint") or reality.get("fingerprint")
        if not pbk:
            _fail("Reality publicKey is missing")
        if not sni:
            _fail("Reality serverName (sni) is missing")
        if not fp:
            _fail("Reality fingerprint is missing")
        _ok("Reality fields publicKey/sni/fingerprint are present")

    direct = by_tag["direct"]
    blocked = by_tag["blocked"]
    if direct.get("protocol") != "freedom":
        _fail("direct outbound protocol must be freedom")
    if blocked.get("protocol") != "blackhole":
        _fail("blocked outbound protocol must be blackhole")
    _ok("direct/blocked outbound protocols are valid")

    routing = data.get("routing") or {}
    _validate_rules(routing.get("rules") or [])

    has_default_proxy = any(
        isinstance(rule, dict)
        and rule.get("outboundTag") == "proxy"
        and rule.get("network") == "tcp,udp"
        for rule in (routing.get("rules") or [])
    )
    if not has_default_proxy:
        _warn("No explicit default proxy catch-all rule found")
    else:
        _ok("Default proxy catch-all rule found")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Проверка smart-link split JSON (доступность URL + базовая валидация Xray структуры)."
    )
    parser.add_argument("--url", required=True, help="Полная ссылка вида http://host:port/split/<token>.json")
    parser.add_argument("--timeout", type=float, default=10.0, help="Таймаут запроса в секундах (по умолчанию: 10)")
    args = parser.parse_args()

    data, _ = fetch_json(args.url, args.timeout)
    validate_xray_config(data)
    print("\n[RESULT] Конфиг прошёл базовую валидацию.")


if __name__ == "__main__":
    main()
