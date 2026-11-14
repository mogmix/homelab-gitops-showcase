---
id: 0001
status: accepted
date: 2026-07-11
---

# ADR 0001 — Edge access model: identity-primary rearchitecture

**Status:** Accepted — implemented and live-verified 2026-07-13.
**Decided:** 2026-07-11 (refined by grilling 2026-07-12).
**Context:** the `jumpserver`/`proxyguard` naming was inverted vs convention; digging in
surfaced a deeper smell in the access mechanism. This ADR is the *why*; the current
mechanics are summarised in `stacks/proxyguard/README.md`.

## The smell

`stacks/proxyguard/data/traefik/config/_common.yaml` defines `whitelistTailscale` as a
hand-enumerated **22-CIDR expansion of `100.64.0.0/10` minus one `/32`** (the
jumpserver's tailnet IP), because "Traefik can't subtract ranges." That artifact
is a *symptom*: an L3 IP allowlist is being forced to express an L7 policy intent
("internet-relayed traffic ≠ a genuine tailnet device").

## Current architecture (facts)

```text
Internet → Cloudflare → Jumpserver (public VPS) → Tailscale → ProxyGuard → Services
                                                   LAN / tailnet devices ↗
```

- **Jumpserver** — public VPS Traefik. `gateway-router` matches
  `HostRegexp('^.+\.example\.com$')` — *everything* — and blind-relays it inward. Does
  **no** access control; only masks 403/404/500 as a generic error page.
- **ProxyGuard** — internal Traefik; **all** access control lives here, in the `mode*`
  middleware chains. No `trustedIPs`, so it matches raw source IP.
- **Mode** = the single source of truth for exposure. `modeLocal` / `modeTailscale` /
  `modePublic`, each with an `*Auth` variant appending tinyauth forward-auth (Pocket ID).
  `modePublic` accepts the jumpserver's relayed traffic; `modeTailscale` fail-closes by
  the CIDR-subtraction hack above.

Upside of today's design: exposure is reasoned about in one file, guarded by
`scripts/hooks/check-traefik-modes.py`. Cost: the outermost hop is a blind `.*` relay with
**no defense in depth** — one mislabeled mode and the internet reaches an internal
service with nothing in between.

## What a bastion / jump host actually is

A **bastion** is a single hardened, audited host that is the *only* sanctioned door from
untrusted → trusted. A **jump host** is that pattern for interactive admin access: you
authenticate *at* it, then hop onward. Defining properties:

1. Authenticated chokepoint (prove identity *at* the door)
2. Terminate & re-originate
3. Sole path in
4. Hardened & audited

The current "jumpserver" satisfies 2 and 3 but **fails 1 — it authenticates nobody.**
It is a relay, not a bastion. Renaming it "bastion" would relocate the lie, not fix it.
Name should follow behaviour.

## The reframe: two axes, currently conflated into "mode"

| Axis | Question | Right mechanism |
| --- | --- | --- |
| **Reachability** | can these packets arrive? | Tailnet ACLs + *one* internet gateway |
| **Authorization** | are *you* allowed *this* service? | Mandatory identity forward-auth |

Key insight: **Tailscale is already the bastion for the trusted population** — every
node proved identity to join, so authenticated entry is already done at L3 by the mesh.
The IP-allowlist gymnastics partly re-implement that at L7. tinyauth + Pocket ID are
already the identity layer, but wired as an *optional* `*Auth` bolt-on rather than the
foundation.

Ideal: the edge is a real bastion **for the internet population only** (the one group
not on the mesh) — terminate public TLS, hand off, nothing else. Inside, reachability is
the tailnet's job and authorization is identity's job. "Mode" collapses from *which IP
ranges* to *which audience*, and the 22-CIDR hack **ceases to exist** rather than being
polished.

## The root fork

- **(A) Network-primary (perimeter/bastion).** IP allowlists stay load-bearing; identity
  is optional. Fix the *mechanism* (kill the 22 CIDRs with a cleaner network signal),
  keep the paradigm.
- **(B) Identity-primary (zero-trust).** Every service behind mandatory identity; network
  position is a coarse pre-filter at most. Jumpserver becomes a true internet-only
  bastion; "mode" becomes about audience.

**Recommendation: (B), phased.** It's where the existing tooling already points and it
dissolves the smell instead of buffing it.

**Blocking cost (the thing that bites):** (B) demands every exposed service tolerate
forward-auth, and some won't: native mobile apps, anything non-HTTP, or anything
carrying its own login. Mandatory identity always grows an exceptions list,
and that list is where zero-trust quietly rots back into a perimeter model.

## Requirements (gathered 2026-07-11)

- Public (no-VPN) access is a **temporary stopgap**: most devices will join the mesh
  eventually; some browser-only clients never will. Design the public tier to shrink.
- Forward-auth-incompatible services needing public reach are rare and must be named.
- Pocket ID SSO per person is acceptable friction on public services.
- The VPS stays — hiding the home IP is deliberate policy.
- Likely future migration Tailscale → NetBird (self-hosted control plane): mechanisms
  must not couple to Tailscale specifics.

**Buy-vs-build:** Pangolin and NetBird were assessed and rejected for this problem.
Pangolin is option (B) productized but moves exposure policy into a UI + database
(GitOps regression) and duplicates Traefik, the overlay, and the identity layer.
NetBird is the wrong layer — the VPS would still be a mesh peer, so the CIDR hack
would reappear verbatim; it remains attractive later as a mesh *transport* swap only.

## Resolved design (2026-07-11, refined by grilling 2026-07-12)

1. **Paradigm: (B) identity-primary.** Public services carry mandatory tinyauth +
   Pocket ID; the mode *names* invert to match (see 5).
2. **Own-auth carve-out.** `modePublicOwnAuth` marks the explicit exceptions: the
   identity layer itself (`auth.` tinyauth, `id.` Pocket ID, which cannot sit behind
   themselves) plus any named app with its own login and MFA. Greppable and
   checker-countable.
3. **Mechanism: dedicated entrypoint.** ProxyGuard gains `relayed` (:8443); the edge
   forwards there. `modePublic*` binds **both** `websecure` and `relayed` (public ⊃
   internal: SSO stays reachable from mesh/LAN if the VPS is down, no trombone for
   insiders); `modeLocal`/`modeTailscale` never bind `relayed` — internet traffic
   can't reach them *by binding*, no IP math. `whitelistTailscale` collapses to a
   single `100.64.0.0/10` (**delete the 22-CIDR block**); `whitelistInternal` is
   **deleted** — public modes carry no IP middleware at all. Mesh-agnostic: NetBird
   uses the same CGNAT range; Tailscale ACLs rejected as mechanism (vendor coupling).
4. **Relayed transport + firewall.** Edge → `https://…:8443` with the existing
   wildcard cert. `relayed` sets `forwardedHeaders.trustedIPs: [<edge tailnet IP>]`
   so real client IPs reach logs and tinyauth (today all internet traffic logs as one
   IP). Safe because an Ansible-managed nftables rule on the proxyguard host enforces
   symmetry: the edge IP may reach **only** :8443, and **only** the edge may reach
   :8443. That rule also closes the regression the CIDR delete would open (a
   compromised edge dialing `modeTailscale` services on :443) — the L3 subtraction
   the 22 CIDRs faked at L7, expressed at L3 where it belongs. Pointer comment in
   `_common.yaml`.
5. **Mode vocabulary inverts at the public tier.** `modePublic` = forward-auth
   mandatory (the default gets the safe behaviour); `modePublicOwnAuth` = the marked
   exception. `modeLocal*`/`modeTailscale*` keep their optional `*Auth` suffix —
   those audiences already authenticated by joining the mesh, so auth genuinely is
   optional there.
6. **Edge posture: no more blind `.*` relay.** A **generated, committed** edge config:
   one router OR-ing the `modePublic*` hostnames, plus a static lowest-priority
   catch-all routing everything else to the local error-page backend (masked page,
   nothing relayed inward). Generator is a sibling of `check-traefik-modes.py`; a
   prek hook regenerates and fails on drift, so exposure changes are reviewable
   diffs. `check-traefik-modes.py` additionally enforces the binding rule:
   `modePublic*` ⇔ binds `relayed`; other modes never. Accidental exposure then
   requires two independent mistakes (wrong mode *and* wrong edge route).
7. **Naming: full rename `jumpserver` → `edge`.** `stacks/edge/`, state path
   `/srv/edge/` (one manual `mv /srv/jumpserver /srv/edge` on the VPS before merge —
   preserves `acme.json`), header `X-From-Edge`, all docs/glossary/comments. VPS
   hostname/tailnet node rename is an optional manual follow-up. `proxyguard` keeps
   its name — accurate for the policy-enforcement point.
8. **The VPS becomes a real gitops host.** Today it is unmanaged (not in inventory,
   config deployed by hand) because it cannot reach Gitea. Fix: the Gitea LXC joins
   the `[tailscale]` group; the VPS pulls `ssh://git@<gitea-tailnet-name>/...` with
   its own read-only deploy key and joins the inventory as `edge`
   (`[gitops]`/`[docker]`/`[tailscale]`). Without this, the generated allowlist (6)
   would not converge and offboarding would need a hand-redeploy. Accepted cost: a
   compromised edge can clone the repo — topology and configs, but no plaintext
   secrets (see 9). Subnet routing was rejected (hands the internet-facing host the
   whole LAN); push-based deploy was rejected (inverts the pull model for one host).
9. **Per-tier age key.** The fleet currently shares one age key; giving it to the VPS
   would let a compromised edge decrypt every secret in the repo. Instead a dedicated
   edge age key is added as a `.sops.yaml` rule for `stacks/edge/.env` (admin key as
   second recipient), and the CF token moves from the untracked
   `secrets/cloudflare_token.txt` docker file-secret to the standard `.env.sops`
   mechanism (Traefik reads `CF_DNS_API_TOKEN` directly). A compromised edge can then
   decrypt exactly the secret it already holds today. This also deletes the fleet's
   only violation of the one-secret-mechanism rule in `CONTEXT.md`.

**Offboarding path:** flip `modePublic*` → `modeTailscale` **and move the DNS
record** from the VPS to the tailnet IP (later codified, see ADR 0008).
Forgetting the DNS step fails closed — the shrunken edge allowlist no longer routes
the name, so it's unreachable, never exposed. The allowlist shrinks automatically
toward "HA app + browser services for the work laptop".

**Cost:** Traefik YAML, one generator script, one nftables rule, one inventory host,
one age key + `.sops.yaml` rule — all in git, reconciled by the existing GitOps loop.
No new services, no UI-managed config, no second overlay.

## Outcome (live-verified 2026-07-13)

Implemented across issues 01–06 and smoke-tested from LAN, internet (via Cloudflare), and
the edge itself — all paths pass. Two rollout facts refined the design:

1. **Explicit `entryPoints` per router.** `dashboardLocal` had none and so implicitly
   bound `relayed`; `check-traefik-modes.py` now requires every router to declare its
   entrypoints.
2. **`relay_guard` (nftables) replaced UFW symmetry.** The `:8443`-only edge restriction
   (design point 4) could not be enforced with UFW: Tailscale's `ts-input` chain precedes
   UFW's, so the edge still reached `modeTailscale*` services on `:443` (confirmed live).
   A dedicated `relay_guard` nftables table (hook priority -10, conntrack exemption, v4+v6
   edge match, logged drops) enforces it instead; the UFW deny rule was deleted as dead.

Also dropped during rollout: `mask-forbidden-errors` (on `modePublic` tinyauth gates
before any backend error is reachable, so masking bought nothing and swallowed real
4xx/5xx — a legitimate OIDC-callback 500 surfaced as a bare 403); and a stale
`whoami.yaml`. Service obscurity now comes from the catch-all (unlisted hostnames) plus
the forward-auth challenge, not from masking public backends.
