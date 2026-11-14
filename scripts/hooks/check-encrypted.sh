#!/bin/sh
status=0
fail() {
  echo "$1"
  status=1
}
for f in "$@"; do
  case "$f" in
    *vault.yaml | *vault.yml)
      # shellcheck disable=SC2016  # The header is literal.
      [ "$(head -c 14 "$f")" = '$ANSIBLE_VAULT' ] || fail "$f:1: not vault-encrypted [ENCRYPT001]"
      ;;
    *.env.sops)
      grep -q '^sops_mac=' "$f" || fail "$f:1: not sops-encrypted [ENCRYPT002]"
      ;;
  esac
done
exit $status
