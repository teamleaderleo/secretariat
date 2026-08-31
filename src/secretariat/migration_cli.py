"""CLI for reviewed value migration from a snapshot home into KDBX."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .backends import BackendError, Tooling
from .config import DeviceConfigError, default_config_path, load_device_config
from .reconcile import ReconcileError, parse_snapshot_spec
from .snapshot_migration import SnapshotMigrationError, migrate_snapshot_home_to_kdbx


def _default_garden_path() -> Path:
    configured = os.environ.get("SECRETARIAT_GARDEN")
    return Path(configured).expanduser() if configured else Path("garden.json")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat migrate")
    value.add_argument("--garden", type=Path, default=_default_garden_path())
    value.add_argument("--json", action="store_true", dest="json_output")
    commands = value.add_subparsers(dest="command", required=True)
    to_kdbx = commands.add_parser(
        "to-kdbx",
        help="Migrate one reviewed Chrome/Edge/Apple snapshot home into the portable KDBX home",
    )
    to_kdbx.add_argument("alias")
    to_kdbx.add_argument("--snapshot", required=True, metavar="SOURCE=PATH")
    return value


def main(arguments: list[str] | None = None) -> int:
    values = list(arguments or [])
    if values and values[0] == "migrate":
        values = values[1:]
    args = parser().parse_args(values)
    try:
        if args.command != "to-kdbx":
            raise SnapshotMigrationError("migration command is unsupported")
        tooling = Tooling.detect()
        if not tooling.pykeepass_available:
            raise BackendError("KDBX migration requires the optional secretariat[kdbx] dependency")
        config = load_device_config(default_config_path())
        if config.kdbx_path is None:
            raise BackendError("KDBX home path is not configured on this device")
        snapshot = parse_snapshot_spec(args.snapshot)

        def unlock() -> str:
            return getpass.getpass("KDBX master password: ")

        result = migrate_snapshot_home_to_kdbx(
            args.garden,
            args.alias,
            snapshot,
            kdbx_path=config.kdbx_path,
            password_provider=unlock,
        )
        if args.json_output:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "action": "migrated-to-kdbx",
                        "alias": result.alias,
                        "kdbx_uuid": result.kdbx_uuid,
                        "home_copy": "portable",
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"migrated {result.alias} to KDBX home copy portable ({result.kdbx_uuid})")
        return 0
    except (SnapshotMigrationError, BackendError, DeviceConfigError, ReconcileError) as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}", file=sys.stderr)
        return 2
