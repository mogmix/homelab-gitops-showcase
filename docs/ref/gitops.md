---
covers:
  - roles/gitops/**
  - playbooks/services/gitops.yaml
---

# GitOps: pull-based stack reconciler

`roles/gitops` installs a self-contained reconcile loop on each host. A systemd timer runs
`docker compose` directly — no Ansible at runtime. Push to `main` → every host converges its
own stacks to git and self-heals.

## How it works

A `gitops-reconcile.timer` (`OnBootSec=1min`, `OnUnitInactiveSec=2min`) fires
`/usr/local/bin/gitops-reconcile.sh`, which:

1. Exits if `/etc/homelab-gitops.disabled` exists (per-host kill switch); takes a `flock` so
   runs never overlap.
2. `git fetch` + `git reset --hard origin/main` — **true convergence**: tracked files are
   reverted to git, so the host *is* `main`. Never runs `git clean`.
3. For each stack in `$STACKS`: if `.env.sops` exists, `sops -d` it to `.env` (regenerated each
   tick, so it stays converged with git); then `cd stacks/<s>` and `docker compose up -d
   --remove-orphans --quiet-pull`. **Skip-gate**: a stack with a `.env.example` but no `.env`
   (and no `.env.sops`) is skipped (not failed), so a host can list a stack before its secret
   is placed.
4. **Teardown pass**: each `stacks/<s>/` dir not in `$STACKS` whose compose project still has
   containers here is `docker compose down --remove-orphans` (never `-v` — named volumes and
   `/srv` bind data stay), then its decrypted `.env` is scrubbed if `.env.sops` exists. A stack
   deleted from the repo entirely is unmatched and needs a manual `down`.
5. Optional `docker image prune -f` if `PRUNE=true`. One failed stack → `rc=1`, others still run.

Idempotent: no-op when state matches, applies config/tag-string changes, and revives a
`docker stop`'d container within ~2 min. Logs to journald (`journalctl -u gitops-reconcile`).

## Config

- `roles/gitops/defaults/main.yaml`: `gitops_repo_url` (SSH deploy key), `gitops_dest`
  (`/opt/homelab`), `gitops_branch`, `gitops_interval`, `gitops_prune`, `gitops_stacks: []`.
- `/etc/homelab-gitops.conf` (sourced by the script): `REPO_DIR`, `BRANCH`, `STACKS`, `PRUNE`.
- Per-host: set `gitops_stacks` in `host_vars`; add the host to `[gitops]` in `hosts.ini`.
- Deploy/update the reconciler (and the age key it writes), then run a synchronous reconcile:
  `just play services/gitops [--limit <host>]` → `playbooks/services/gitops.yaml`. The timer
  only pulls/decrypts/`compose up`, so key or role changes need this play re-run, not just a tick.

## Secrets

- **One shared read-only deploy key**: private half in ansible-vault (`vault_gitops_deploy_key`),
  installed to `~/.ssh/gitops_deploy`; repo uses it via `git config core.sshCommand`. Registered
  once in Gitea. The internet-facing `edge` host is the exception: it carries its **own**
  read-only key (`vault_edge_deploy_key`) and pulls over the tailnet
  (`ssh://git@{{ gitea_tailnet_host }}/...`), and its **own** age key (`vault_edge_age_key`,
  scoped by the edge rule in `.sops.yaml`). A compromised edge can reuse neither fleet key.
- **One shared age key** (SOPS): private half in ansible-vault (`vault_gitops_age_key`),
  installed to `~/.config/sops/age/keys.txt`; public recipient in `.sops.yaml`. Stack secrets
  live encrypted in git as `stacks/<s>/.env.sops` and are decrypted to `.env` on the host each
  tick, with no manual placement. An operator admin key is a second recipient on every rule
  (break-glass and re-encryption).
- Any remaining manual `.env` / `secrets/*.txt` stay **untracked** on the host beside
  `compose.yaml`. `git reset --hard` leaves untracked files alone, so secrets survive every
  reconcile.
- **Gitea host key is pinned, not TOFU'd**: `gitops_gitea_host_key` (plain, public var) is
  written into the gitops user's `known_hosts` every play run, keyed to the host (and port, if
  non-default) parsed from `gitops_repo_url`, overwriting any stale or rotated entry. A re-run of
  `just play services/gitops` self-heals a host whose entry drifted, instead of trust-on-first-use
  silently wedging the fetch. This is Gitea's **built-in SSH server** key, not the guest's sshd
  key; refresh it with `ssh-keyscan` against the Gitea SSH endpoint.

## Deliberately omitted

- No Gitea webhook receiver — the 2-min timer alone gives self-healing convergence.
- No per-host keypair generation — one shared vault-distributed deploy key. Same for the
  age key: one identity decrypts every fleet `.env.sops` (edge excepted, above), so any
  compromised gitops host exposes all stack secrets, including stacks it never runs. Per-host
  recipients in `.sops.yaml` would cap that blast radius, at the cost of re-encrypting every
  secret on host changes.
- No Watchtower/force-pull. Floating tags (`:release`) do **not** auto-advance; image updates
  are tag-string-driven. Refreshing floating tags is a separate, manually-run concern.
