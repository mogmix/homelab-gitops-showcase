---
id: 0008
status: accepted
date: 2026-11-08
covers:
  - inventories/example/group_vars/all/dns_records.yaml
  - playbooks/services/dns.yaml
  - scripts/hooks/check-dns-records.py
enforced-by: prek.toml
---

# Manage DNS records as code

## Context

DNS was edited by hand at the public DNS provider and on the internal resolver. Retiring or re-tiering a service meant remembering a manual record move; forgetting it caused an outage of the identity names (`auth.`/`id.`), which still resolved to a host that no longer served them.

## Decision

`dns_records.yaml` declares homelab-owned records in `cloudflare_records` (public zone) and `unbound_records` (internal split-horizon overrides). `playbooks/services/dns.yaml` applies them from the control machine, reviewed with `--check --diff`. Management is non-authoritative: unlisted records stay untouched, and removal needs an explicit `state: absent`. The `dns-records` hook checks every ProxyGuard router hostname against the declared records and router modes: a non-public router must never resolve to a public address.

## Rejected

- Terraform provider modules: adds a state backend and its locking for a few dozen records.
- A read-only verifier with hand-managed records: still leaves the manual step that caused the outage.

## Reversal condition

Revisit if the zone gains enough hand-managed records that non-authoritative management hides drift, or if Terraform state handling is adopted for other infrastructure.
