"""CLI for value-verified, metadata-only replica retirement."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .backends import BackendError, Tooling, backend_for
from .config import DeviceConfigError, default_config_path, load_device_config
from .kdbx_agent import KDBXAgentClient, KDBXAgentError
from .reconcile import ReconcileError, parse_snapshot_spec
from .replica_retirement import (
    ReplicaRetirementError,
    retire_replica_from_receipt,
    verify_replica_convergence,
    write_replica_receipt,
)


def _default_garden_path() -> Path:
    configured = os.environ.get("SECRETARIAT_GARDEN")
    return Path(configured).expanduser() if configured else Path("garden.json")


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat")
    value.add_argument("--garden", type=Path, default=_default_garden_path())
    value.add_argument("--json", action="store_true", dest="json_output")
    top = value.add_subparsers(dest="top_command", required=True)
    replica = top.add_parser("replica", help="Verify and retire credential replicas")
    commands = replica.add_subparsers(dest="command", required=True)

    verify = commands.add_parser(
        "verify",
        help="Compare one snapshot replica to the current readable home and write a secret-free receipt",
    )
    verify.add_argument("alias")
    verify.add_argument("--copy-id", required=True)
    verify.add_argument("--snapshot", required=True, metavar="SOURCE=PATH")
    verify.add_argument("--receipt", required=True, type=Path)

    retire = commands.add_parser(
        "retire",
        help="Remove one Garden replica described by a convergence receipt; external source data is untouched",
    )
    retire.add_argument("--receipt", required=True, type=Path)
    retire.add_argument(
        "--ack-attached-data",
        action="store_true",
        help="Acknowledge that the external source has notes or OTP metadata before forgetting the replica",
    )
    return value


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    try:
        if args.command == "verify":
            tooling = Tooling.detect()
            config = load_device_config(default_config_path())
            snapshot = parse_snapshot_spec(args.snapshot)
            agent = KDBXAgentClient()

            def load_home(source):
                if source.type == "kdbx" and agent.available():
                    try:
                        return agent.load(source)
                    except KDBXAgentError as error:
                        raise BackendError(str(error)) from error
                return backend_for(source, tooling, device_config=config).load(source)

            receipt = verify_replica_convergence(
                args.garden,
                args.alias,
                args.copy_id,
                snapshot,
                load_home=load_home,
            )
            write_replica_receipt(receipt, args.receipt)
            payload = {
                "ok": True,
                "action": "replica-verified",
                "alias": receipt.alias,
                "home_copy": receipt.home.id,
                "replica_copy": receipt.replica.id,
                "replica_source": receipt.replica.type,
                "matching_rows": receipt.matching_rows,
                "notes_present": receipt.notes_present,
                "otp_present": receipt.otp_present,
                "receipt": str(args.receipt),
            }
            if args.json_output:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    f"verified replica {receipt.replica.id} matches home {receipt.home.id}; "
                    f"receipt: {args.receipt}"
                )
                if receipt.attached_data_present:
                    attached = []
                    if receipt.notes_present:
                        attached.append("notes")
                    if receipt.otp_present:
                        attached.append("OTP metadata")
                    print("external source carries " + " and ".join(attached) + "; review before retirement")
            return 0

        if args.command == "retire":
            receipt = retire_replica_from_receipt(
                args.garden,
                args.receipt,
                acknowledge_attached_data=args.ack_attached_data,
            )
            payload = {
                "ok": True,
                "action": "replica-retired",
                "alias": receipt.alias,
                "retired_copy": receipt.replica.id,
                "external_source": receipt.replica.type,
                "external_deleted": False,
                "attached_data_present": receipt.attached_data_present,
            }
            if args.json_output:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(
                    f"retired Garden replica {receipt.replica.id} for {receipt.alias}; "
                    f"external {receipt.replica.type} data was not deleted"
                )
                if receipt.attached_data_present:
                    print("attached external notes/OTP metadata was acknowledged; source-side cleanup remains manual")
            return 0

        raise ReplicaRetirementError("replica command is unsupported")
    except (ReplicaRetirementError, BackendError, DeviceConfigError, ReconcileError) as error:
        if args.json_output:
            print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        else:
            print(f"secretariat: {error}", file=sys.stderr)
        return 2
