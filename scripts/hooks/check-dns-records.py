#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Check declared DNS records against ProxyGuard router hostnames and modes."""

import ipaddress
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "stacks/proxyguard/data/traefik/config"
RECORDS = ROOT / "inventories/example/group_vars/all/dns_records.yaml"
TYPES = {
    "cloudflare_records": {"A", "AAAA", "CNAME"},
    "unbound_records": {"A", "AAAA"},
}
# Tailnet addresses sit in shared CGNAT space, which `is_private` does not cover.
TAILNET = ipaddress.ip_network("100.64.0.0/10")


def internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return ip.is_private or ip in TAILNET


def covers(name: str, host: str) -> bool:
    if name.startswith("*."):
        return host.endswith(name[1:])
    return name == host


def main() -> int:
    rc = 0

    def fail(msg: str) -> None:
        nonlocal rc
        print(msg)
        rc = 1

    declared = yaml.safe_load(RECORDS.read_text()) or {}
    records = []
    for backend in ("cloudflare_records", "unbound_records"):
        for rec in declared.get(backend) or []:
            if rec.get("type") not in TYPES[backend]:
                fail(
                    f"{RECORDS}:1: {backend} '{rec.get('name')}' has type "
                    f"'{rec.get('type')}', only {'/'.join(sorted(TYPES[backend]))} allowed [DNS001]"
                )
            elif rec.get("state") != "absent":
                records.append((backend, rec))

    for path in sorted(ROUTERS.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text()) or {}
        for name, router in ((data.get("http") or {}).get("routers") or {}).items():
            mode = next(
                (
                    str(m)
                    for m in (router or {}).get("middlewares") or []
                    if str(m).startswith("mode")
                ),
                "",
            )
            for host in re.findall(
                r"Host\(`([^`]+)`\)", str((router or {}).get("rule"))
            ):
                hits = [(b, r) for b, r in records if covers(str(r["name"]), host)]
                if not hits:
                    fail(
                        f"{path}:1: router '{name}' host '{host}' has no declared record [DNS002]"
                    )
                if mode.startswith("modePublic"):
                    continue
                for backend, rec in hits:
                    target = str(rec["target"])
                    try:
                        ip = ipaddress.ip_address(target)
                    except ValueError:
                        ip = None
                    if ip is None or not internal(ip):
                        fail(
                            f"{RECORDS}:1: {backend} '{rec['name']}' -> {target} "
                            f"serves {mode or 'unmoded'} router '{name}' ('{host}') "
                            "but is not a tailnet or private address [DNS003]"
                        )
    return rc


if __name__ == "__main__":
    sys.exit(main())
