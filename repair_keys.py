#!/usr/bin/env python3
"""
One-shot maintenance tool:
1) Fixes protocol=http for servers stored as https on port 80.
2) Re-pushes key settings from DB to panel for configured keys.

Run from project root where config.py exists.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Iterable

from database.connection import get_db


@dataclass
class PushStats:
    total: int = 0
    ok: int = 0
    failed: int = 0


def fix_protocols_for_port_80(dry_run: bool) -> int:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, host, port, COALESCE(protocol, '') AS protocol
            FROM servers
            WHERE port = 80 AND (protocol IS NULL OR TRIM(protocol) = '' OR LOWER(protocol) = 'https')
            ORDER BY id
            """
        ).fetchall()
        if not rows:
            print("[servers] no https:80 records found")
            return 0

        print("[servers] candidates to fix (https:80 -> http):")
        for row in rows:
            print(f"  - id={row['id']} name={row['name']} host={row['host']} protocol={row['protocol'] or '<empty>'}")

        if dry_run:
            print("[servers] dry-run mode, no DB update")
            return len(rows)

        conn.execute(
            """
            UPDATE servers
            SET protocol = 'http'
            WHERE port = 80 AND (protocol IS NULL OR TRIM(protocol) = '' OR LOWER(protocol) = 'https')
            """
        )
        print(f"[servers] updated: {len(rows)}")
        return len(rows)


def collect_key_ids(target_key_id: int | None) -> list[int]:
    if target_key_id is not None:
        return [target_key_id]

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id
            FROM vpn_keys
            WHERE server_id IS NOT NULL
              AND panel_inbound_id IS NOT NULL
              AND panel_email IS NOT NULL
              AND TRIM(panel_email) <> ''
              AND client_uuid IS NOT NULL
              AND TRIM(client_uuid) <> ''
            ORDER BY id
            """
        ).fetchall()
        return [int(r["id"]) for r in rows]


async def repush_keys(key_ids: Iterable[int], dry_run: bool, reset_traffic: bool) -> PushStats:
    from database.requests import get_vpn_key_by_id
    from bot.services.vpn_api import push_key_to_panel

    stats = PushStats()
    for key_id in key_ids:
        stats.total += 1
        key = get_vpn_key_by_id(key_id)
        if not key:
            print(f"[key {key_id}] skip: not found")
            stats.failed += 1
            continue

        email = key.get("panel_email")
        server_name = key.get("server_name")
        server_active = bool(key.get("server_active"))
        protocol = key.get("protocol") or "<empty>"
        port = key.get("port")
        host = key.get("host")
        print(
            f"[key {key_id}] server={server_name} {protocol}://{host}:{port} "
            f"email={email} active={server_active}"
        )

        if dry_run:
            continue

        ok = await push_key_to_panel(key_id, reset_traffic=reset_traffic)
        if ok:
            print(f"[key {key_id}] OK")
            stats.ok += 1
        else:
            print(f"[key {key_id}] FAIL")
            stats.failed += 1

    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description="Repair panel protocol and re-push keys to VPN panels")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes only")
    parser.add_argument("--key-id", type=int, default=None, help="Repair and push only one key id")
    parser.add_argument(
        "--reset-traffic",
        action="store_true",
        help="Reset up/down traffic counters on panel before pushing key data",
    )
    args = parser.parse_args()

    print("=== step 1/2: protocol fix ===")
    fix_protocols_for_port_80(args.dry_run)

    print("=== step 2/2: key push ===")
    key_ids = collect_key_ids(args.key_id)
    if not key_ids:
        print("[keys] no configured keys found")
        return 0

    stats = await repush_keys(key_ids, args.dry_run, args.reset_traffic)
    print(f"[summary] total={stats.total} ok={stats.ok} failed={stats.failed} dry_run={args.dry_run}")

    from bot.services.vpn_api import close_all_clients

    await close_all_clients()
    return 0 if args.dry_run or stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
