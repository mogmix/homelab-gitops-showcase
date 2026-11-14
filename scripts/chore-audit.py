#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml"]
# ///
"""Deterministic chore audit: the mechanical half of repository housekeeping.

Read-only. Prints findings (stale refs, script rot, inventory drift, dead
stacks, zero-match prek patterns) and exits 1 on any. Nothing here is a
judgment call, so it is safe to run from a mandatory gate.

`--advisories` additionally runs the heuristics (relic comments, floating image
tags, unassigned stacks), which are listed but never fail.
`--pins` additionally prints the pin map (every image/_version pin found).
"""

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "inventories/example"

RELIC_RE = re.compile(
    r"#.*(migrat|legacy|old instance|previously|used to|no longer|carried over"
    r"|preserve existing|for the migration|Step [0-9])",
    re.IGNORECASE,
)
FLOATING_RE = re.compile(
    r"image:.*:(latest|release|alpine|stable|cuda|cpu|main|edge)\b", re.IGNORECASE
)
PIN_RE = re.compile(r"(?:^|[^a-z])image:|_version:", re.IGNORECASE)

findings: list[str] = []
advisories: list[str] = []


def finding(path: str, code: str, message: str, line: int = 1) -> None:
    findings.append(f"{path}:{line}: {message} [{code}]")


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def walk(*dirs: str, suffixes: tuple[str, ...]) -> list[Path]:
    out = []
    for d in dirs:
        base = ROOT / d
        if base.exists():
            out += [
                p
                for p in sorted(base.rglob("*"))
                if p.is_file() and p.suffix in suffixes
            ]
    return out


def doc_files() -> list[Path]:
    return sorted(ROOT.glob("*.md")) + walk("docs", suffixes=(".md",))


def just_recipes() -> set[str]:
    names = set()
    for line in (ROOT / "justfile").read_text().splitlines():
        m = re.match(r"^@?([a-zA-Z][\w-]*)([^:]*)?:(?!=)", line)
        if m:
            names.add(m.group(1))
    return names


def check_just_playbooks() -> None:
    """Recipes naming a playbook that no longer exists — how `just validate` rotted."""
    for m in re.finditer(
        r"\bplaybooks/[\w/-]+\.yaml\b", (ROOT / "justfile").read_text()
    ):
        if not (ROOT / m.group(0)).exists():
            finding("justfile", "CHORE001", f"references nonexistent {m.group(0)}")


def check_doc_refs() -> None:
    recipes = just_recipes()
    for md in doc_files():
        if md.is_relative_to(ROOT / "docs/adr"):
            continue  # ADRs are history — references to since-deleted files are expected
        text = md.read_text()
        code = re.findall(r"`([^`]+)`", text)
        for block in re.findall(r"```.*?```", text, re.DOTALL):
            code += block.splitlines()
        for span in code:
            for m in re.finditer(r"\bjust\s+([a-z][a-z0-9-]+)\b", span):
                if m.group(1) not in recipes:
                    finding(
                        rel(md),
                        "CHORE002",
                        f"references nonexistent recipe `just {m.group(1)}`",
                    )
        for m in re.finditer(r"\bscripts/([\w.-]+/)*[\w.-]+\.(?:sh|py)\b", text):
            if not (ROOT / m.group(0)).exists():
                finding(rel(md), "CHORE003", f"references nonexistent {m.group(0)}")


def check_md_links() -> None:
    for md in doc_files():
        for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", md.read_text()):
            target = m.group(1).split("#")[0]
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (md.parent / target).exists():
                finding(rel(md), "CHORE004", f"dead link {m.group(1)}")


HOOK_CONFIG = ROOT / "prek.toml"


def check_scripts() -> None:
    referenced = "".join(
        (ROOT / f).read_text()
        for f in ("justfile", "ansible.cfg", "prek.toml", "mise.toml")
    ) + "".join(p.read_text() for p in walk("docs", suffixes=(".md",)))
    for script in sorted(p for p in (ROOT / "scripts").rglob("*") if p.is_file()):
        name = rel(script)
        text = script.read_text()
        if name not in referenced:
            finding(
                name,
                "CHORE005",
                "not referenced from justfile, hook config, ansible.cfg, or docs",
            )
        # A file with no shebang is sourced, not run, so executability is wrong.
        if text.startswith("#!") and not script.stat().st_mode & 0o111:
            finding(name, "CHORE006", "not executable")
        if script.suffix == ".py":
            if (
                "uv run --script" not in text.splitlines()[0]
                or "# /// script" not in text
            ):
                finding(name, "CHORE007", "missing uv script shebang or PEP 723 block")
            try:
                ast.parse(text)
            except SyntaxError as e:
                finding(name, "CHORE008", f"syntax error: {e.msg}", e.lineno or 1)
        elif script.suffix == ".sh":
            r = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
            if r.returncode:
                finding(name, "CHORE009", f"bash -n failed: {r.stderr.strip()}")


def check_prek_patterns() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    config = tomllib.loads(HOOK_CONFIG.read_text())
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            pattern = hook.get("files")
            # always_run hooks are deliberately armed before their first match.
            if not pattern or hook.get("always_run"):
                continue
            exclude = hook.get("exclude", r"(?!)")
            if not any(
                re.search(pattern, f) and not re.search(exclude, f) for f in tracked
            ):
                finding(
                    rel(HOOK_CONFIG),
                    "CHORE010",
                    f"hook {hook['id']} `files:` matches no tracked file",
                )


def parse_inventory() -> tuple[set[str], dict[str, set[str]]]:
    hosts, groups = set(), {}
    current = None
    for raw in (INVENTORY / "hosts.ini").read_text().splitlines():
        if re.match(r"^#\s*\S+\s+ansible_host=", raw):
            finding(
                "inventories/example/hosts.ini",
                "CHORE011",
                f"commented-out host: {raw.strip()}",
            )
        line = raw.split("#")[0].strip()
        if not line:
            continue
        if m := re.match(r"^\[(\S+)\]$", line):
            current = m.group(1)
            groups[current] = set()
        elif current is None:
            hosts.add(line.split()[0])
        else:
            groups[current].add(line.split()[0])
    return hosts, groups


def check_inventory() -> None:
    hosts, groups = parse_inventory()
    grouped = set().union(*groups.values())
    for host in sorted(hosts - grouped):
        finding("inventories/example/hosts.ini", "CHORE012", f"{host} is in no group")
    for host in sorted(grouped - hosts):
        finding(
            "inventories/example/hosts.ini",
            "CHORE013",
            f"{host} is in a group but never defined",
        )
    for host in sorted(groups.get("gitops", set()) - groups.get("docker", set())):
        finding(
            "inventories/example/hosts.ini",
            "CHORE014",
            f"{host} is in [gitops] but not [docker]",
        )
    for host in sorted(groups.get("gitops", set())):
        if host not in gitops_stacks_by_host():
            finding(
                "inventories/example/hosts.ini",
                "CHORE015",
                f"{host} is in [gitops] but has no gitops_stacks in host_vars",
            )


def gitops_stacks_by_host() -> dict[str, list[str]]:
    out = {}
    for vars_file in sorted(INVENTORY.glob("host_vars/*/vars.yaml")):
        data = yaml.safe_load(vars_file.read_text()) or {}
        if "gitops_stacks" in data:
            out[vars_file.parent.name] = data["gitops_stacks"]
    return out


def deployed_stacks() -> set[str]:
    return {s for stacks in gitops_stacks_by_host().values() for s in stacks}


def on_disk_stacks() -> set[str]:
    return {p.name for p in (ROOT / "stacks").iterdir() if p.is_dir()}


def check_stacks() -> None:
    # Only this direction is unambiguous: the reconciler breaks on a real host.
    for name in sorted(deployed_stacks() - on_disk_stacks()):
        finding(
            "inventories/example",
            "CHORE016",
            f"gitops_stacks references missing stacks/{name}/",
        )


def advise_unassigned_stacks() -> None:
    # Unassigned reads the same whether the stack is orphaned or merely not wired
    # up yet, so it's a judgment call — advisory, not a gate failure.
    for name in sorted(on_disk_stacks() - deployed_stacks()):
        advisories.append(f"stacks/{name}/: not in any host's gitops_stacks")


def advise_relics() -> None:
    for f in walk(
        "playbooks",
        "roles",
        "inventories",
        suffixes=(".yaml", ".yml", ".j2", ".cfg", ".ini"),
    ):
        if f.name == "vault.yaml":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if RELIC_RE.search(line):
                advisories.append(f"{rel(f)}:{i}: relic comment? {line.strip()[:100]}")


def pin_lines() -> list[tuple[Path, int, str]]:
    out = []
    for f in walk(
        "stacks", "roles", "playbooks", "inventories", suffixes=(".yaml", ".yml", ".j2")
    ):
        if f.name == "vault.yaml":
            continue
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if PIN_RE.search(line) and "ansible" not in line.lower():
                out.append((f, i, line.strip()))
    return out


def advise_floating() -> None:
    for f, i, line in pin_lines():
        if FLOATING_RE.search(line):
            advisories.append(f"{rel(f)}:{i}: floating tag: {line[:100]}")


def main() -> int:
    args = sys.argv[1:]
    for check in (
        check_just_playbooks,
        check_doc_refs,
        check_md_links,
        check_scripts,
        check_prek_patterns,
        check_inventory,
        check_stacks,
    ):
        check()
    if "--advisories" in args:
        for advise in (
            advise_unassigned_stacks,
            advise_relics,
            advise_floating,
        ):
            advise()
    if "--pins" in args:
        print("== pins ==")
        for f, i, line in pin_lines():
            print(f"{rel(f)}:{i}: {line}")
        print()
    if advisories:
        print("== advisories (judgment calls — not failures) ==")
        print("\n".join(advisories))
        print()
    if findings:
        print("== findings ==")
        print("\n".join(dict.fromkeys(findings)))
        return 1
    print("chore audit: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
