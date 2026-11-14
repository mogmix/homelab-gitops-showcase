---
covers:
  - roles/gitea_runner/**
  - playbooks/services/gitea_runner.yaml
---

# Gitea Actions runner

`ci-runner` (a dedicated VM) runs Gitea Actions jobs for a throwaway CI organization.
The runner binary is downloaded at a pinned version and verified against a pinned SHA-256
before install.

## Isolation

- Trusted jobs only. The VM has LAN reach and no network isolation, so a malicious
  dependency in a job could reach other hosts. Fork pull-request triggers are never enabled.
- The runner registers at org scope with one container label, `ubuntu-latest`; there is no
  host label, so no job runs directly on the VM.
- Job containers set `privileged: false`, `docker_host: "-"` and `valid_volumes: []`: no Docker
  socket, no arbitrary mounts. The runner user is in the `docker` group, which is
  root-equivalent on the VM; that is why the VM is single-purpose.
- The VM holds no infrastructure credentials. The registration token exists only in the vault
  (`vault_gitea_runner_registration_token`), is passed as an environment variable at
  registration under `no_log`, and is never written to the VM.
- `/var/lib/gitea-runner/.runner` is the persistent runner identity (mode 0600). Treat it as a
  secret.

## Operate

```bash
just play services/gitea_runner --limit ci-runner   # install, register once, start
ssh admin@ci-runner 'sudo journalctl -u gitea-runner -n 50 --no-pager'
ssh admin@ci-runner 'sudo systemctl restart gitea-runner'
```

Restart is safe: the daemon waits up to 2h50m for running jobs (`shutdown_timeout`).

## Recover

- **Runner offline or lost identity:** remove the runner in the org's Settings → Actions →
  Runners, delete `/var/lib/gitea-runner/.runner`, generate a new registration token, replace
  the vault value, and rerun the playbook.
- **VM lost:** recreate it from the VM template, bootstrap it, then rerun the playbook with a
  fresh token.

## Smoke test

Commit this to a test repository as `.gitea/workflows/smoke.yaml`; it must pass on the runner.
It proves DNS, HTTPS to Gitea, public registry access, and that no Docker socket reaches a job.

```yaml
on:
  workflow_dispatch:
  push:
    branches: [main]
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - run: getent hosts git.int.example.com
      - run: curl -fsS -o /dev/null https://git.int.example.com
      - run: curl -fsS -o /dev/null https://pypi.org/simple/pip/
      - run: test ! -S /var/run/docker.sock
```

## Credential-bearing workflows

Fixtures that need credentials live in the throwaway CI org, never under the owner account.
Package-write rights are owner-wide, so the org bounds the blast radius.

- Each token is scoped to the minimum (`read:package` + `write:package`) and stored as a
  repository secret, never an org-level or runner-global one.
- Credential-bearing workflows trigger only on `push` to `main` or `workflow_dispatch`, and
  guard every job with `github.ref == 'refs/heads/main' && github.actor == '<owner>'`. They
  never use `pull_request*` triggers.
- Gitea ignores `jobs.<id>.environment`, so there are no environment approvals; the `if` guards
  are the only gate. Negative checks (non-`main` ref, fork PR, other actor) must pass before any
  untrusted trigger is enabled.
