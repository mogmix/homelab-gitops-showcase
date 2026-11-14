user := env('HOMELAB_USER', 'admin')

# List available recipes
[default]
help:
    @just --list

# Install Ansible and Galaxy collections, then enable Git hooks (requires global prek)
[group('setup')]
install:
    mise install
    mise exec -- ansible-galaxy install -r requirements.yaml
    prek install

# Update pinned hook revisions for human review
[group('setup')]
hooks-update:
    prek autoupdate

# Regenerate the edge relay allowlist.
[group('generate')]
edge-config:
    ./scripts/hooks/generate-edge-config.py --write

# Run a playbook as $HOMELAB_USER (usage: `just play services/gitops --limit gitops-1`)
[group('ansible')]
play name *args:
    ansible-playbook 'playbooks/{{ name }}.yaml' -u '{{ user }}' {{ args }}

# Ping a host, loading its vars and the vault (usage: `just ping proxy`)
[group('ansible')]
ping host:
    ansible '{{ host }}' -u '{{ user }}' -m ping

# Show every version and image pin
[group('report')]
pins:
    ./scripts/chore-audit.py --pins

# Edit a group_vars vault in $EDITOR (usage: `just vault [group]`)
[group('vault')]
vault group='all':
    ansible-vault edit ./inventories/example/group_vars/'{{ group }}'/vault.yaml

# Re-encrypt stack .env files newer than their .env.sops (`--force` reseals all — use after an age-key rotation)
[group('vault')]
encrypt-envs *args:
    ./scripts/encrypt-envs.sh {{ args }}

# Show gitops-reconcile logs on a host (usage: `just gitops-logs <host> [lines]`)
[arg('lines', pattern='^[0-9]+$')]
[group('ansible')]
gitops-logs host lines='50':
    ansible '{{ host }}' -u '{{ user }}' -b -m command -a "journalctl -u gitops-reconcile.service -n {{ lines }} --no-pager"
