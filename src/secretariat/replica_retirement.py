"""Verify snapshot replicas against a readable home and retire Garden metadata from a receipt."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .backends import BackendError
from .garden import Copy, GardenError, load_garden
from .garden_edit import GardenEditError, _entry, _read, _write
from .reconcile import SnapshotSpec
from .snapshot_migration import (
    SNAPSHOT_HOME_TYPES,
    SnapshotMigrationError,
    select_snapshot_account_value,
)


RECEIPT_SCHEMA_VERSION = 1
MAX_RECEIPT_BYTES = 64 * 1024
ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "alias",
        "verified_at",
        "username",
        "login",
        "home",
        "replica",
        "source_metadata",
    }
)
COPY_FIELDS = frozenset({"id", "type", "reference"})
SOURCE_METADATA_FIELDS = frozenset({"notes_present", "otp_present", "matching_rows"})


class ReplicaRetirementError(BackendError):
    """Bounded replica retirement failure containing metadata only."""


@dataclass(frozen=True)
class ReplicaReceipt:
    alias: str
    verified_at: str
    username: str | None
    login: str
    home: Copy
    replica: Copy
    notes_present: bool
    otp_present: bool
    matching_rows: int

    @property
    def attached_data_present(self) -> bool:
        return self.notes_present or self.otp_present

    def document(self) -> dict[str, Any]:
        return {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "alias": self.alias,
            "verified_at": self.verified_at,
            "username": self.username,
            "login": self.login,
            "home": _copy_document(self.home),
            "replica": _copy_document(self.replica),
            "source_metadata": {
                "notes_present": self.notes_present,
                "otp_present": self.otp_present,
                "matching_rows": self.matching_rows,
            },
        }


def verify_replica_convergence(
    garden_path: Path,
    alias: str,
    copy_id: str,
    snapshot: SnapshotSpec,
    *,
    load_home: Callable[[Copy], str],
    now: Callable[[], datetime] | None = None,
) -> ReplicaReceipt:
    garden = load_garden(garden_path)
    try:
        entry = garden.by_alias(alias)
        home = entry.home_copy()
        replica = entry.copy_by_id(copy_id)
    except GardenError as error:
        raise ReplicaRetirementError(str(error)) from error
    if entry.kind != "password":
        raise ReplicaRetirementError("replica convergence verification supports password credentials only")
    if replica.id == home.id:
        raise ReplicaRetirementError("the current home copy cannot be retired as a replica")
    if replica.type not in SNAPSHOT_HOME_TYPES:
        raise ReplicaRetirementError("target replica is not a Chrome, Edge, or Apple snapshot copy")
    if snapshot.source != replica.type:
        raise ReplicaRetirementError("snapshot source does not match the target replica copy")
    login = entry.links.get("login")
    if not login:
        raise ReplicaRetirementError("credential requires an explicit Garden login URL before replica verification")

    try:
        snapshot_selection = select_snapshot_account_value(entry.links["login"], entry.username or "", snapshot)
    except SnapshotMigrationError as error:
        raise ReplicaRetirementError(str(error)) from error
    try:
        home_value = load_home(home)
    except BackendError as error:
        raise ReplicaRetirementError(str(error)) from error
    if not isinstance(home_value, str) or not home_value:
        raise ReplicaRetirementError("credential home returned no password value")
    if not hmac.compare_digest(home_value, snapshot_selection.value):
        raise ReplicaRetirementError("target replica does not match the current home password")

    timestamp = (now or (lambda: datetime.now(timezone.utc)))()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return ReplicaReceipt(
        alias=entry.alias,
        verified_at=timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        username=entry.username,
        login=login,
        home=home,
        replica=replica,
        notes_present=snapshot_selection.notes_present,
        otp_present=snapshot_selection.otp_present,
        matching_rows=snapshot_selection.matching_rows,
    )


def write_replica_receipt(receipt: ReplicaReceipt, path: Path) -> None:
    target = path.expanduser()
    if target.exists() or target.is_symlink():
        raise ReplicaRetirementError("replica receipt path already exists")
    if not target.parent.is_dir():
        raise ReplicaRetirementError("replica receipt parent directory is unavailable")
    payload = (json.dumps(receipt.document(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > MAX_RECEIPT_BYTES:
        raise ReplicaRetirementError("replica receipt exceeds the reviewed byte bound")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise ReplicaRetirementError("replica receipt could not be created") from error
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise ReplicaRetirementError("replica receipt could not be written") from error


def load_replica_receipt(path: Path) -> ReplicaReceipt:
    target = path.expanduser()
    try:
        if target.is_symlink():
            raise ReplicaRetirementError("replica receipt path must not be a symbolic link")
        stat_result = target.stat()
    except OSError as error:
        raise ReplicaRetirementError("replica receipt could not be inspected") from error
    if not target.is_file() or stat_result.st_size <= 0 or stat_result.st_size > MAX_RECEIPT_BYTES:
        raise ReplicaRetirementError("replica receipt is unavailable or exceeds the reviewed bound")
    try:
        document = json.loads(target.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReplicaRetirementError("replica receipt is not valid UTF-8 JSON") from error
    return parse_replica_receipt(document)


def parse_replica_receipt(document: Any) -> ReplicaReceipt:
    root = _object(document, "replica receipt")
    if set(root) != ROOT_FIELDS or root.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ReplicaRetirementError("replica receipt schema is unsupported")
    alias = _text(root.get("alias"), "replica receipt alias")
    verified_at = _text(root.get("verified_at"), "replica receipt timestamp")
    try:
        datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReplicaRetirementError("replica receipt timestamp is invalid") from error
    username = root.get("username")
    if username is not None:
        username = _text(username, "replica receipt username")
    login = _text(root.get("login"), "replica receipt login", maximum=2_048)
    home = _parse_copy(root.get("home"), "receipt home")
    replica = _parse_copy(root.get("replica"), "receipt replica")
    if home.id == replica.id:
        raise ReplicaRetirementError("replica receipt home and replica ids must differ")
    metadata = _object(root.get("source_metadata"), "replica source metadata")
    if set(metadata) != SOURCE_METADATA_FIELDS:
        raise ReplicaRetirementError("replica source metadata fields are invalid")
    notes = metadata.get("notes_present")
    otp = metadata.get("otp_present")
    rows = metadata.get("matching_rows")
    if not isinstance(notes, bool) or not isinstance(otp, bool):
        raise ReplicaRetirementError("replica source metadata flags are invalid")
    if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1 or rows > 20_000:
        raise ReplicaRetirementError("replica source matching row count is invalid")
    return ReplicaReceipt(alias, verified_at, username, login, home, replica, notes, otp, rows)


def retire_replica_from_receipt(
    garden_path: Path,
    receipt_path: Path,
    *,
    acknowledge_attached_data: bool = False,
) -> ReplicaReceipt:
    receipt = load_replica_receipt(receipt_path)
    if receipt.attached_data_present and not acknowledge_attached_data:
        details = []
        if receipt.notes_present:
            details.append("notes")
        if receipt.otp_present:
            details.append("OTP metadata")
        raise ReplicaRetirementError(
            "target source carries " + " and ".join(details) + "; use --ack-attached-data after reviewing it"
        )

    try:
        garden_file = _read(garden_path)
        entry = _entry(garden_file.document, receipt.alias)
        _verify_entry_matches_receipt(entry, receipt)
        entry["copies"] = [copy for copy in entry["copies"] if copy.get("id") != receipt.replica.id]
        _write(garden_file)
    except GardenEditError as error:
        raise ReplicaRetirementError(str(error)) from error
    return receipt


def _verify_entry_matches_receipt(entry: dict[str, Any], receipt: ReplicaReceipt) -> None:
    current_home_id = entry.get("home")
    copies = entry.get("copies")
    if not isinstance(copies, list):
        raise ReplicaRetirementError("Garden credential copies are invalid")
    if current_home_id is None and len(copies) == 1:
        current_home_id = copies[0].get("id")
    current_home = _copy_by_id(copies, current_home_id)
    current_replica = _copy_by_id(copies, receipt.replica.id)
    if current_home != _copy_document(receipt.home):
        raise ReplicaRetirementError("Garden home changed since replica verification")
    if current_replica != _copy_document(receipt.replica):
        raise ReplicaRetirementError("Garden replica changed since replica verification")
    if entry.get("username") != receipt.username:
        raise ReplicaRetirementError("Garden username changed since replica verification")
    links = entry.get("links") or {}
    if not isinstance(links, dict) or links.get("login") != receipt.login:
        raise ReplicaRetirementError("Garden login changed since replica verification")
    if receipt.replica.id == current_home_id:
        raise ReplicaRetirementError("verified replica became the Garden home and cannot be retired")


def _copy_by_id(copies: list[Any], copy_id: Any) -> dict[str, Any]:
    matches = [copy for copy in copies if isinstance(copy, dict) and copy.get("id") == copy_id]
    if len(matches) != 1:
        raise ReplicaRetirementError("Garden copy from replica receipt is no longer present exactly once")
    return matches[0]


def _copy_document(copy: Copy) -> dict[str, str]:
    return {"id": copy.id, "type": copy.type, "reference": copy.reference}


def _parse_copy(value: Any, label: str) -> Copy:
    raw = _object(value, label)
    if set(raw) != COPY_FIELDS:
        raise ReplicaRetirementError(f"{label} fields are invalid")
    copy_id = _text(raw.get("id"), f"{label} id")
    copy_type = _text(raw.get("type"), f"{label} type")
    reference = _text(raw.get("reference"), f"{label} reference")
    return Copy(copy_id, copy_type, reference)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReplicaRetirementError(f"{label} must be a JSON object")
    return value


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise ReplicaRetirementError(f"{label} is invalid")
    return value
