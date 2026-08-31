"""Metadata-only browser bridge setup commands."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .browser_protocol import HOST_NAME


EXTENSION_ID = re.compile(r"^[a-p]{32}$")


class BrowserSetupError(ValueError):
    pass


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat browser")
    value.add_argument("--json", action="store_true", dest="json_output")
    commands = value.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("manifest", help="Render a Chrome/Edge native-host manifest")
    manifest.add_argument("--extension-id", required=True)
    manifest.add_argument("--host-path", required=True, type=Path)

    config = commands.add_parser("config-snippet", help="Render the browser authorization config snippet")
    config.add_argument("--extension-id", required=True)
    return value


def main(arguments: list[str] | None = None) -> int:
    values = _strip_browser_command(list(arguments or []))
    args = parser().parse_args(values)
    try:
        extension_origin = _extension_origin(args.extension_id)
        if args.command == "manifest":
            host_path = args.host_path.expanduser()
            if not host_path.is_absolute() or len(str(host_path)) > 4_096:
                raise BrowserSetupError("native host path must be an absolute path")
            document = {
                "name": HOST_NAME,
                "description": "Secretariat browser credential bridge",
                "path": str(host_path),
                "type": "stdio",
                "allowed_origins": [extension_origin],
            }
        elif args.command == "config-snippet":
            document = {"browser": {"allowed_extension_origins": [extension_origin]}}
        else:
            raise BrowserSetupError("browser setup command is unsupported")
        print(json.dumps(document, indent=2, sort_keys=True))
        return 0
    except BrowserSetupError as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}")
        return 2


def _strip_browser_command(values: list[str]) -> list[str]:
    for index, value in enumerate(values):
        if value == "browser":
            return values[:index] + values[index + 1 :]
        if value not in {"--json"}:
            break
    return values


def _extension_origin(extension_id: str) -> str:
    if not isinstance(extension_id, str) or not EXTENSION_ID.fullmatch(extension_id):
        raise BrowserSetupError("extension id must be 32 lowercase characters from a through p")
    return f"chrome-extension://{extension_id}/"
