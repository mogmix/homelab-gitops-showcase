#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["jinja2"]
# ///
"""Parse-check Jinja templates without resolving Ansible filters or lookups."""

import sys

from jinja2 import Environment
from jinja2.exceptions import TemplateSyntaxError


def main() -> int:
    rc = 0
    env = Environment()
    for path in sys.argv[1:]:
        with open(path) as f:
            source = f.read()
        try:
            env.parse(source, filename=path)
        except TemplateSyntaxError as exc:
            print(f"{path}:{exc.lineno}: {exc.message} [JINJA001]")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
