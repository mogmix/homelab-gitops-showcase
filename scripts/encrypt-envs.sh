#!/usr/bin/env bash
# Re-encrypt stack .env files to the recipients in .sops.yaml.
# Default: reseal only when the plaintext .env is newer than its .env.sops.
# --force: reseal every .env unconditionally — needed after an age-key rotation,
# where the plaintext is unchanged but the .sops.yaml recipient moved (the mtime
# guard would otherwise skip it and leave the ciphertext bound to the old key).
set -euo pipefail
shopt -s nullglob

force=0
[ "${1:-}" = "--force" ] && force=1

cd "$(dirname "$0")/.." || exit 1

for f in stacks/*/.env; do
  if [[ "$force" -eq 1 || ! -f "$f.sops" || "$f" -nt "$f.sops" ]]; then
    sops -e "$f" >"$f.sops"
    echo "encrypted $f"
  fi
done
