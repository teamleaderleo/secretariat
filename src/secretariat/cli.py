"""Secretariat command-line interface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from .audit import AuditError, audit_repository
from .backends import BackendError, Tooling, backend_for, copy_paste_once
from .config import DeviceConfigError, default_config_path, load_device_config
from .garden import Entry, GardenError, load_garden
from .reconcile import ReconcileError, Report, parse_snapshot_spec, reconcile
from .report import write_reconciliation_html


def _default_garden_path() -> Path:
    configured = os.environ.get("SECRETARIAT_GARDEN")
    return Path(configured).expanduser() if configured else Path("garden.json")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat")
    value.add_argument("--garden", type=Path, default=_default_garden_path())
    value.add_argument("--json", action="store_true", dest="json_output")
    commands = value.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="List secret-free credential metadata")
    find = commands.add_parser("find", help="Search the Garden")
    find.add_argument("query")
    show = commands.add_parser("show", help="Show one Garden entry")
    show.add_argument("alias")
    due = commands.add_parser("due", help="List credentials due for rotation or expiry")
    due.add_argument("--days", type=int, default=30)
    commands.add_parser("doctor", help="Inspect the Garden and optional machine helpers")
    put = commands.add_parser("put", help="Store one value in an implemented home copy")
    put.add_argument("alias")
    copy = commands.add_parser("copy", help="Copy one home value through a paste-once clipboard")
    copy.add_argument("alias")
    run = commands.add_parser("run", help="Inject one home value into one child process")
    run.add_argument("alias")
    run.add_argument("child", nargs=argparse.REMAINDER)
    reconcile_parser = commands.add_parser(
        "reconcile",
        help="Compare temporary password-manager CSV snapshots without printing values",
    )
    reconcile_parser.add_argument(
        "--snapshot",
        action="append",
        required=True,
        metavar="SOURCE=PATH",
        help="Temporary snapshot from chrome_passwords, edge_passwords, or apple_passwords",
    )
    reconcile_parser.add_argument(
        "--html",
        type=Path,
        metavar="PATH",
        help="Write a private, secret-free interactive HTML review report",
    )
    commands.add_parser("audit", help="Scan tracked and untracked files for obvious secret material")
    return value


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        if args.command == "audit":
            return _audit(args)
        if args.command == "reconcile":
            return _reconcile(args)
        garden = load_garden(args.garden)
        tooling = Tooling.detect()
        if args.command == "list":
            _render_entries(garden.entries, args.json_output)
        elif args.command == "find":
            _render_entries(garden.find(args.query), args.json_output)
        elif args.command == "show":
            _render_entry(garden.by_alias(args.alias), args.json_output)
        elif args.command == "due":
            if args.days < 0 or args.days > 3_650:
                raise GardenError("due window must be between zero and 3650 days")
            cutoff = date.today() + timedelta(days=args.days)
            entries = tuple(
                entry
                for entry in garden.entries
                if entry.status in {"active", "rotating"}
                and entry.due_on() is not None
                and entry.due_on() <= cutoff
            )
            _render_entries(entries, args.json_output)
        elif args.command == "doctor":
            _doctor(garden, tooling, args.json_output)
        elif args.command == "put":
            _put(garden.by_alias(args.alias), tooling)
        elif args.command == "copy":
            _copy(garden.by_alias(args.alias), tooling)
        elif args.command == "run":
            return _run(garden.by_alias(args.alias), tooling, args.child)
        else:
            raise GardenError("command is unsupported")
        return 0
    except (GardenError, BackendError, AuditError, ReconcileError, DeviceConfigError) as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}", file=sys.stderr)
        return 2


def _entry_view(entry: Entry) -> dict[str, object]:
    return {
        "alias": entry.alias,
        "title": entry.title,
        "kind": entry.kind,
        "provider": entry.provider,
        "purpose": entry.purpose,
        "environment": entry.environment,
        "status": entry.status,
        "scopes": list(entry.scopes),
        "copies": [
            {"id": copy.id, "type": copy.type, "reference": copy.reference}
            for copy in entry.copies
        ],
        "home": entry.home if entry.home is not None else entry.copies[0].id,
        "delivery": (
            {"type": entry.delivery.type, "name": entry.delivery.name}
            if entry.delivery is not None
            else None
        ),
        "created_at": _iso(entry.created_at),
        "expires_at": _iso(entry.expires_at),
        "rotate_by": _iso(entry.rotate_by),
        "last_tested_at": _iso(entry.last_tested_at),
        "due_on": _iso(entry.due_on()),
        "public_fingerprint": entry.public_fingerprint,
        "links": entry.links,
        "notes": entry.notes,
    }


def _render_entry(entry: Entry, json_output: bool) -> None:
    if json_output:
        print(json.dumps({"schema_version": 3, "entry": _entry_view(entry)}, indent=2))
        return
    view = _entry_view(entry)
    for key, value in view.items():
        if isinstance(value, (dict, list)) or value is None:
            rendered = json.dumps(value, sort_keys=True)
        else:
            rendered = str(value)
        print(f"{key}: {rendered}")


def _render_entries(entries: tuple[Entry, ...], json_output: bool) -> None:
    if json_output:
        print(json.dumps({"schema_version": 3, "entries": [_entry_view(e) for e in entries]}, indent=2))
        return
    for entry in entries:
        due = entry.due_on().isoformat() if entry.due_on() else "none"
        home = entry.home_copy()
        print(
            f"{entry.alias}\t{entry.status}\t{entry.provider}\t{home.type}\t"
            f"copies={len(entry.copies)}\tdue={due}\t{entry.title}"
        )


def _doctor(garden, tooling: Tooling, json_output: bool) -> None:
    source_types = sorted({copy.type for entry in garden.entries for copy in entry.copies})
    config = load_device_config(default_config_path())

    def support(source_type: str) -> str:
        if source_type == "secret_service":
            return "available" if tooling.secret_tool else "helper_missing"
        if source_type == "kdbx":
            if not tooling.pykeepass_available:
                return "dependency_missing"
            if config.kdbx_path is None:
                return "config_missing"
            return "available" if config.kdbx_path.is_file() else "file_missing"
        return "indexed_only"

    source_support = {source_type: support(source_type) for source_type in source_types}
    report = {
        "schema_version": 3,
        "garden": "valid",
        "entry_count": len(garden.entries),
        "copy_count": sum(len(entry.copies) for entry in garden.entries),
        "source_types": source_types,
        "source_support": source_support,
        "secret_service_helper": "available" if tooling.secret_tool else "missing",
        "macos_security_cli": "available" if tooling.macos_security else "missing",
        "paste_once_clipboard": "available" if tooling.wl_copy else "missing",
        "kdbx_library": "available" if tooling.pykeepass_available else "missing",
        "kdbx_path": "configured" if config.kdbx_path is not None else "missing",
        "kdbx_file": (
            "available"
            if config.kdbx_path is not None and config.kdbx_path.is_file()
            else "missing"
        ),
        "value_storage_fallback": "forbidden",
        "process_environment_exposure": "selected child process tree and same-user inspection",
    }
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")


def _home_backend(entry: Entry, tooling: Tooling):
    home = entry.home_copy()
    if home.type == "kdbx" and entry.kind == "passkey":
        raise BackendError("passkeys require a platform credential-provider or exchange adapter")
    return home, backend_for(home, tooling)


def _put(entry: Entry, tooling: Tooling) -> None:
    home, backend = _home_backend(entry, tooling)
    value = getpass.getpass(f"Value for {entry.alias}: ")
    confirmation = getpass.getpass("Repeat value: ")
    if not value or value != confirmation:
        raise BackendError("credential values were empty or did not match")
    backend.store(home, value, entry.title)
    print(f"stored {entry.alias} in home copy {home.id}; no value was printed")


def _copy(entry: Entry, tooling: Tooling) -> None:
    home, backend = _home_backend(entry, tooling)
    value = backend.load(home)
    copy_paste_once(value, tooling)
    print(f"copied {entry.alias} from home copy {home.id} to a paste-once clipboard")


def _run(entry: Entry, tooling: Tooling, child: list[str]) -> int:
    if child and child[0] == "--":
        child = child[1:]
    if not child:
        raise GardenError("run requires a child command after --")
    if entry.delivery is None or entry.delivery.type != "env":
        raise GardenError("credential has no environment delivery")
    home, backend = _home_backend(entry, tooling)
    value = backend.load(home)
    environment = os.environ.copy()
    environment[entry.delivery.name] = value
    try:
        result = subprocess.run(child, env=environment, check=False)
    except OSError as error:
        raise BackendError("child process could not be started") from error
    return result.returncode


def _reconcile(args) -> int:
    specs = tuple(parse_snapshot_spec(value) for value in args.snapshot)
    report = reconcile(specs)
    if args.html is not None:
        write_reconciliation_html(report, args.html)
    _render_reconciliation(report, args.json_output)
    if args.html is not None and not args.json_output:
        print(f"HTML review: {args.html}")
    return 0


def _render_reconciliation(report: Report, json_output: bool) -> None:
    if json_output:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "snapshot_count": report.snapshot_count,
                    "observation_count": report.observation_count,
                    "counts": report.counts(),
                    "multi_account_origins": list(report.multi_account_origins),
                    "groups": [
                        {
                            "origin": group.origin,
                            "username": group.username,
                            "classification": group.classification,
                            "copies": group.copies,
                            "sources": list(group.sources),
                            "source_counts": dict(group.source_counts),
                            "note_sources": list(group.note_sources),
                            "otp_sources": list(group.otp_sources),
                        }
                        for group in report.groups
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    counts = report.counts()
    print(
        f"snapshots={report.snapshot_count} observations={report.observation_count} "
        f"single={counts['single']} duplicate={counts['duplicate']} "
        f"conflict={counts['conflict']} multi_account_sites={counts['multi_account_origins']}"
    )
    for group in report.groups:
        sources = ", ".join(
            f"{source}x{count}" if count > 1 else source for source, count in group.source_counts
        )
        extras = []
        if group.note_sources:
            extras.append("notes=" + ",".join(group.note_sources))
        if group.otp_sources:
            extras.append("otp=" + ",".join(group.otp_sources))
        suffix = ("\t" + " ".join(extras)) if extras else ""
        print(f"{group.classification}\t{group.origin}\t{group.username}\t{sources}{suffix}")


def _audit(args) -> int:
    root = Path.cwd()
    findings = audit_repository(root)
    if args.json_output:
        print(
            json.dumps(
                {
                    "ok": not findings,
                    "findings": [finding.__dict__ for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    elif findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.rule}", file=sys.stderr)
    else:
        print("no obvious credential values found in repository files")
    return 0 if not findings else 1


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
