---
covers:
  - roles/renovate/**
  - playbooks/renovate.yaml
  - renovate.json5
---

# Renovate

Self-hosted Renovate opens one reviewable pull request per version-pin update on the
self-hosted Gitea and keeps one Dependency Dashboard issue. Nothing merges automatically:
a human merge to `main` is the deploy, because the GitOps reconciler converges every host to
`main` within minutes. What it tracks is in [`renovate.json5`](../../renovate.json5).

`roles/renovate` runs on `gitops-1` (the `[renovate]` inventory group). A `renovate.timer`
fires `renovate.service` daily; the service is a oneshot `docker run --rm` of the pinned image
(`renovate_image`). The container publishes no ports and mounts no Docker socket. It is a
systemd timer, not a stack under `stacks/`, so `gitops-reconcile` never restarts it.

What it bumps:

- Compose image tags in `stacks/*/compose.yaml` (exact tags, never floating).
- Ansible Galaxy collection pins in `requirements.yaml`.
- Tool pins in `mise.toml`.
- Any `*_version` variable in the inventory annotated with
  `# renovate: datasource=... depName=...`.

Policy in `renovate.json5`: Traefik updates arrive as one grouped pull request across both
proxies; stateful services with irreversible migrations wait for Dashboard approval; Galaxy
roles stay manual.

Non-goals: Watchtower and force-pull. Floating tags do not auto-advance; every image change
is a reviewed diff.

The container is limited to `renovate_memory`; exit status 137 in
`journalctl -u renovate.service`, or an `oom-kill` line in `journalctl -k`, means raise it.

## Credentials (operator, names only)

| Secret | Scope | Lands in |
| --- | --- | --- |
| `vault_renovate_gitea_token` | Gitea bot token: `repo`, `user`, `issue`, `organization`. The bot user needs write access to the one repository. | `RENOVATE_TOKEN` |
| `vault_renovate_github_token` | read-only github.com token, for changelogs | `GITHUB_COM_TOKEN` |

Both live in the host's ansible-vault file. The role templates them into the root-only
`/etc/renovate.env` (mode `0600`, `no_log`), which the service passes with `--env-file`. They are
never in the unit file, the process list, or the repository.

## Deploy

```sh
just play renovate
```

Re-running is idempotent. Rotating a token is an edit of the vault value plus the same run.

## Manual first run

```sh
ssh admin@gitops-1 sudo systemctl start renovate.service
ssh admin@gitops-1 sudo journalctl -u renovate.service --no-pager
```

`start` blocks until the oneshot finishes. Check `systemctl list-timers renovate.timer` for the
next daily run.
