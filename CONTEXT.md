# Homelab

A GitOps-managed homelab: Ansible provisions hosts, a pull-based reconciler
converges Docker stacks to git, and two Traefik instances gate access. This is the
glossary of terms specific to that setup — not a spec.

## Fleet & hosts

**Host**:
Any machine Ansible manages — an entry in the inventory's `hosts.ini`. Bare metal
or LXC alike.
_Avoid_: server, box, machine, VM (when you mean a managed inventory entry)

**Node**:
The Proxmox hypervisor specifically. Reserved for the host node; a plain
managed host is not a "node".
_Avoid_: node (for anything other than the Proxmox hypervisor)

**Guest**:
An LXC container running on the node. Membership in the `[lxc]` group marks a host as
an Ansible-provisioned guest.
_Avoid_: container (ambiguous with Docker containers), VM

**GitOps host**:
A host in the `[gitops]` group that runs the reconcile loop and serves Docker stacks
from git.
_Avoid_: reconciler host, stack host

## GitOps & reconciliation

**Stack**:
A Docker Compose project living under `stacks/<name>/`. The unit the reconciler
converges — one stack, one compose project, one directory.
_Avoid_: app, service (a "service" is a Compose service _within_ a stack), project

**Reconcile**:
One timer-driven run of `gitops-reconcile.sh`: fetch, `git reset --hard origin/main`,
then bring every listed stack up. A single pass is a "tick".
_Avoid_: sync, deploy, apply

**Convergence**:
The invariant the reconcile enforces — after a tick the host's tracked files _are_
`main`. Not a one-off action; the steady state.
_Avoid_: sync, drift-correction

**Skip-gate**:
The rule that a stack with a `.env.example` but no `.env`/`.env.sops` is skipped, not
failed — a host may list a stack before its secret is placed.
_Avoid_: pending stack, blocked stack

**Teardown pass**:
The phase of a tick that runs `docker compose down` on stack dirs present in the tree
but absent from `$STACKS`. Never uses `-v`; data survives.
_Avoid_: cleanup, prune (prune means image prune here)

**Kill switch**:
The `/etc/homelab-gitops.disabled` marker file that halts reconciling on one host.
_Avoid_: pause, disable flag

## Proxy & access

**Edge**:
The public VPS Traefik instance — an internet-only bastion. Relays only the generated
allowlist of `modePublic*` hostnames (`relay.yaml`) to ProxyGuard's `relayed`
entrypoint; every other hostname gets a masked error page, nothing relayed inward.
It serves nothing of its own.
_Avoid_: jumpserver, bastion, gateway, VPS (when you mean the Traefik role it plays)

**ProxyGuard**:
The internal Traefik instance and policy-enforcement point: the `mode*` middleware
chains of `_common.yaml` decide authorization. Together with the edge allowlist,
accidental exposure needs two independent mistakes.
_Avoid_: the proxy (ambiguous — there are two), reverse proxy

**Mode**:
The exposure a Traefik router picks — exactly one, and the source of truth the edge
allowlist is generated from: `modeLocal`/`modeTailscale` (optional `*Auth` variant),
`modePublic` (tinyauth forward-auth mandatory), `modePublicOwnAuth` (the marked
carve-out for services with their own login). Only `modePublic*` binds `relayed`.
_Avoid_: tier, access level, exposure level

**Tailnet**:
The Tailscale network. `modeTailscale` allows the whole CGNAT range
(`100.64.0.0/10`); internet traffic is excluded by entrypoint binding, not IP math.
_Avoid_: VPN, mesh

## Storage & secrets

**Config-as-code**:
Files git owns and _wants_ to converge (`traefik.yaml`, `config/*.yaml`). Mounted
read-only so the app can never write state into the tree.
_Avoid_: config files (the point is git-owned + `:ro`)

**Runtime state**:
Bytes the app owns (DBs, `acme.json`, app data). Lives outside the checkout under
`/srv/<stack>/` on local disk, mounted read-write.
_Avoid_: data, volumes (too broad)

**Bulk media**:
Large libraries (photos, documents) under `/mnt/nas/<stack>/` on the NAS. Databases
never go here — they stay on local `/srv`.
_Avoid_: media, files

**Secret**:
A credential in a per-stack `.env`, encrypted at rest in git as `.env.sops` (SOPS +
age) and decrypted on the host each tick. The one secret mechanism — Docker `secrets:`
are deliberately not used.
_Avoid_: env file (a `.env` may hold non-secret config too), credential store
