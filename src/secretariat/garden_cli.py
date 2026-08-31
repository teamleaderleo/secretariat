"""CLI for explicit, secret-free Garden metadata mutations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .garden_edit import GardenEditError, add_entry, attach_copy, detach_copy, set_home, set_login


def _default_garden_path() -> Path:
    configured = os.environ.get("SECRETARIAT_GARDEN")
    return Path(configured).expanduser() if configured else Path("garden.json")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat")
    value.add_argument("--garden", type=Path, default=_default_garden_path())
    value.add_argument("--json", action="store_true", dest="json_output")
    top = value.add_subparsers(dest="command", required=True)
    garden = top.add_parser("garden", help="Edit secret-free Garden metadata")
    commands = garden.add_subparsers(dest="garden_command", required=True)

    add = commands.add_parser("add", help="Add one logical credential with its first copy")
    add.add_argument("--alias", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--kind", required=True)
    add.add_argument("--provider", required=True)
    add.add_argument("--copy-id", required=True)
    add.add_argument("--copy-type", required=True)
    add.add_argument("--reference", required=True)

    attach = commands.add_parser("attach", help="Attach another copy to an existing credential")
    attach.add_argument("--alias", required=True)
    attach.add_argument("--copy-id", required=True)
    attach.add_argument("--copy-type", required=True)
    attach.add_argument("--reference", required=True)
    attach.add_argument("--home", action="store_true", help="Make the attached copy authoritative")

    home = commands.add_parser("set-home", help="Choose the authoritative copy")
    home.add_argument("--alias", required=True)
    home.add_argument("--copy-id", required=True)

    login = commands.add_parser("set-login", help="Set the credential-free HTTPS login URL")
    login.add_argument("--alias", required=True)
    login.add_argument("--url", required=True)

    detach = commands.add_parser("detach", help="Remove a replica from a logical credential")
    detach.add_argument("--alias", required=True)
    detach.add_argument("--copy-id", required=True)
    detach.add_argument("--new-home", help="Required when detaching the current home")
    return value


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        if args.garden_command == "add":
            add_entry(
                args.garden,
                alias=args.alias,
                title=args.title,
                kind=args.kind,
                provider=args.provider,
                copy_id=args.copy_id,
                copy_type=args.copy_type,
                reference=args.reference,
            )
            return _success(args, "added", alias=args.alias, copy_id=args.copy_id)
        if args.garden_command == "attach":
            attach_copy(
                args.garden,
                alias=args.alias,
                copy_id=args.copy_id,
                copy_type=args.copy_type,
                reference=args.reference,
                make_home=args.home,
            )
            return _success(args, "attached", alias=args.alias, copy_id=args.copy_id)
        if args.garden_command == "set-home":
            set_home(args.garden, alias=args.alias, copy_id=args.copy_id)
            return _success(args, "home-set", alias=args.alias, copy_id=args.copy_id)
        if args.garden_command == "set-login":
            set_login(args.garden, alias=args.alias, url=args.url)
            return _success(args, "login-set", alias=args.alias)
        if args.garden_command == "detach":
            detach_copy(
                args.garden,
                alias=args.alias,
                copy_id=args.copy_id,
                new_home=args.new_home,
            )
            return _success(args, "detached", alias=args.alias, copy_id=args.copy_id)
        raise GardenEditError("Garden command is unsupported")
    except GardenEditError as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}", file=sys.stderr)
        return 2


def _success(args, action: str, *, alias: str, copy_id: str | None = None) -> int:
    payload = {"ok": True, "action": action, "alias": alias}
    if copy_id is not None:
        payload["copy_id"] = copy_id
    if args.json_output:
        print(json.dumps(payload, sort_keys=True))
    else:
        suffix = f" copy={copy_id}" if copy_id is not None else ""
        print(f"{action}: {alias}{suffix}")
    return 0
