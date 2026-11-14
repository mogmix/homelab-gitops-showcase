#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Check public SOPS recipient metadata against .sops.yaml without decrypting."""

import glob
import re
import sys

import yaml


def expected_recipients(rules, plaintext_path):
    """Recipients SOPS would use for plaintext_path: the first matching creation rule."""
    for rule in rules:
        if re.search(rule["path_regex"], plaintext_path):
            return {r.strip() for r in rule["age"].split(",")}
    return None


def actual_recipients(sops_path):
    """Recipients embedded in a dotenv .env.sops file."""
    found = set()
    with open(sops_path) as fh:
        for line in fh:
            m = re.match(r"sops_age__list_\d+__map_recipient=(\S+)", line)
            if m:
                found.add(m.group(1))
    return found


def main() -> int:
    rc = 0

    def fail(msg: str) -> None:
        nonlocal rc
        print(msg)
        rc = 1

    with open(".sops.yaml") as fh:
        rules = yaml.safe_load(fh)["creation_rules"]

    for sops_path in sorted(glob.glob("stacks/*/.env.sops")):
        plaintext_path = sops_path[: -len(".sops")]
        want = expected_recipients(rules, plaintext_path)
        if want is None:
            fail(
                f".sops.yaml:1: no creation rule matches {plaintext_path} "
                f"for {sops_path} [SOPS001]"
            )
            continue
        have = actual_recipients(sops_path)
        if have != want:
            fail(
                f"{sops_path}:1: recipient drift: encrypted to {sorted(have)}, "
                f".sops.yaml wants {sorted(want)} — reseal with "
                f"`sops updatekeys -y --input-type dotenv {sops_path}` [SOPS002]"
            )

    return rc


if __name__ == "__main__":
    sys.exit(main())
