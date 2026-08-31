"""Top-level Secretariat command dispatcher."""

from __future__ import annotations

import sys

from . import browser_cli, cli, garden_cli


def main(arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    command = _top_command(values)
    if command == "garden":
        return garden_cli.main(values)
    if command == "browser":
        return browser_cli.main(values)
    return cli.main(values)


def _top_command(arguments: list[str]) -> str | None:
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value == "--json":
            index += 1
            continue
        if value == "--garden":
            index += 2
            continue
        if value.startswith("--garden="):
            index += 1
            continue
        if value.startswith("-"):
            return None
        return value
    return None
