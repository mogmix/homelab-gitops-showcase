---
id: 0007
status: accepted
date: 2026-08-30
covers:
  - prek.toml
  - justfile
enforced-by: prek.toml
---

# Use one three-group prek contract

## Context

Validation policy was split between prek hook stages and Just recipes. The surfaces
disagreed about which checks wrote files and which files an agent covered. A correct agent
loop needs one policy and explicit paths.

## Decision

Use `prek.toml` as the only validation policy, with exactly `format`, `check`, and `verify`
groups. Agents name their owned paths directly on the manual-stage commands.

## Rules

- `format` MUST contain only idempotent rewriters.
- File-local verdicts MUST belong to both `check` and `verify`.
- Whole-repository verdicts MUST belong only to `verify` and receive no filenames.
- Just recipes MUST NOT wrap prek groups.

## Rejected

- Keep validation behind Just recipes. This preserves two command surfaces whose policy and
  file scopes can drift.
- Use hook stages as validation tiers. Stages answer when Git runs a hook, not which complete
  verdict an agent needs while editing or finishing.
- Compute edit and final scopes before invoking prek. The caller must name the files it
  actually owns explicitly instead of relying on a repository-wide scope convention.
