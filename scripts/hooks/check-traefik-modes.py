#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Require explicit exposure modes and entrypoints on ProxyGuard routers."""

import sys

import yaml


def main() -> int:
    rc = 0

    def fail(msg: str) -> None:
        nonlocal rc
        print(msg)
        rc = 1

    for path in sys.argv[1:]:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        routers = (data.get("http") or {}).get("routers") or {}
        for name, router in routers.items():
            middlewares = (router or {}).get("middlewares") or []
            entrypoints = (router or {}).get("entryPoints") or []
            public = any(str(m).startswith("modePublic") for m in middlewares)
            if not any(str(m).startswith("mode") for m in middlewares):
                fail(f"{path}:1: router '{name}' has no mode* middleware [TRAEFIK001]")
            if not entrypoints:
                fail(
                    f"{path}:1: router '{name}' declares no entryPoints "
                    "(would implicitly bind all, including 'relayed') [TRAEFIK002]"
                )
            elif public != ("relayed" in entrypoints):
                fail(
                    f"{path}:1: router '{name}' violates the binding rule: "
                    "modePublic* <=> binds 'relayed' [TRAEFIK003]"
                )
    return rc


if __name__ == "__main__":
    sys.exit(main())
