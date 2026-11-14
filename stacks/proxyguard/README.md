# ProxyGuard

The internal Traefik instance and the single policy-enforcement point for every
HTTP service. See [ADR 0001](../../docs/adr/0001-edge-access-model.md) for the why.

## What's included

- **Traefik**: file provider only. No Docker socket, so a container label can never
  publish a route.
- **tinyauth**: forward-auth middleware, mandatory on `modePublic`.
- **Pocket ID**: OIDC provider behind tinyauth (passkeys).

## Configuration model

- `data/traefik/traefik.yaml` is static config; `data/traefik/config/*.yaml` is dynamic
  and hot-reloaded. Both are git-owned and mounted `:ro`.
- `_common.yaml` defines the `mode*` middleware chains. Every router picks exactly one.
- Entrypoints: `websecure` (:443) for LAN and tailnet, `relayed` (:8443) for traffic the
  edge relays. Only `modePublic*` routers bind `relayed`.

| Mode | Audience | Binds `relayed` | Auth |
| --- | --- | --- | --- |
| `modeLocal` | LAN | no | optional (`modeLocalAuth`) |
| `modeTailscale` | tailnet (`100.64.0.0/10`) | no | optional (`modeTailscaleAuth`) |
| `modePublic` | internet via edge | yes | tinyauth, mandatory |
| `modePublicOwnAuth` | internet via edge | yes | the service's own login (marked carve-out) |

## Guard rails

- `scripts/hooks/check-traefik-modes.py`: every router declares a mode and explicit
  entrypoints, and `modePublic*` binds `relayed` and nothing else does.
- `scripts/hooks/generate-edge-config.py`: regenerates the edge allowlist from the
  `modePublic*` routers and fails on drift.
- `roles/relay_guard`: nftables pins :8443 to the edge and the edge to :8443.

## Secrets

`.env.example` shows the shape. The real values are committed only as `.env.sops`
and decrypted on the host by the reconciler.
