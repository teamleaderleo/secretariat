"""Explicit one-credential migration from a reviewed snapshot home into KDBX."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .backends import BackendError, add_kdbx_entry
from .garden import GardenError, load_garden
from .garden_edit import (
    GardenEditError,
    commit_prepared,
    prepare_attach_copy,
    set_prepared_copy_reference,
)
from .reconcile import SnapshotSpec, normalize_origin, read_snapshot


SNAPSHOT_HOME_TYPES = frozenset({"chrome_passwords", "edge_passwords", "apple_passwords"})
PORTABLE_COPY_ID = "portable"
PLACEHOLDER_KDBX_UUID = "0" * 32


class SnapshotMigrationError(BackendError):
    """Bounded migration failure that never includes a credential value."""


class SnapshotMigrationOrphanError(SnapshotMigrationError):
    """A KDBX entry exists but the preflighted Garden promotion did not commit."""

    def __init__(self, *, alias: str, garden_path: Path, kdbx_uuid: str) -> None:
        super().__init__(
            f"KDBX entry {kdbx_uuid} was created but the Garden was not changed; attach the UUID deliberately"
        )
        self.alias = alias
        self.garden_path = garden_path
        self.kdbx_uuid = kdbx_uuid

    @property
    def recovery_argv(self) -> tuple[str, ...]:
        return (
            "secretariat",
            "--garden",
            str(self.garden_path),
            "garden",
            "attach",
            "--alias",
            self.alias,
            "--copy-id",
            PORTABLE_COPY_ID,
            "--copy-type",
            "kdbx",
            "--reference",
            self.kdbx_uuid,
            "--home",
        )


@dataclass(frozen=True)
class MigrationSelection:
    alias: str
    title: str
    username: str
    login: str
    source: str
    value: str = field(repr=False)


@dataclass(frozen=True)
class MigrationResult:
    alias: str
    kdbx_uuid: str


def select_snapshot_value(garden_path: Path, alias: str, snapshot: SnapshotSpec) -> MigrationSelection:
    garden = load_garden(garden_path)
    try:
        entry = garden.by_alias(alias)
    except GardenError as error:
        raise SnapshotMigrationError("credential alias was not found") from error
    if entry.kind != "password":
        raise SnapshotMigrationError("snapshot-to-KDBX migration supports password credentials only")
    home = entry.home_copy()
    if home.type not in SNAPSHOT_HOME_TYPES:
        raise SnapshotMigrationError("credential home is not a Chrome, Edge, or Apple snapshot copy")
    if snapshot.source != home.type:
        raise SnapshotMigrationError("snapshot source does not match the credential's current home copy")
    login = entry.links.get("login")
    if not login:
        raise SnapshotMigrationError("credential requires an explicit Garden login URL before migration")
    target_origin = normalize_origin(login)
    username = entry.username or ""
    username_key = username.strip().casefold()

    observations = read_snapshot(snapshot)
    matches = tuple(
        observation
        for observation in observations
        if observation.origin == target_origin and observation.username_key == username_key
    )
    if not matches:
        raise SnapshotMigrationError("snapshot contains no row matching the Garden login origin and username")
    first = matches[0].password
    if any(not hmac.compare_digest(first, observation.password) for observation in matches[1:]):
        raise SnapshotMigrationError("snapshot source contains conflicting passwords for this Garden account")
    if not first:
        raise SnapshotMigrationError("snapshot matching row has an empty password")
    return MigrationSelection(
        alias=entry.alias,
        title=entry.title,
        username=username,
        login=login,
        source=home.type,
        value=first,
    )


def migrate_snapshot_home_to_kdbx(
    garden_path: Path,
    alias: str,
    snapshot: SnapshotSpec,
    *,
    kdbx_path: Path,
    password_provider: Callable[[], str],
    add_entry: Callable[..., str] = add_kdbx_entry,
) -> MigrationResult:
    selection = select_snapshot_value(garden_path, alias, snapshot)

    try:
        prepared = prepare_attach_copy(
            garden_path,
            alias=selection.alias,
            copy_id=PORTABLE_COPY_ID,
            copy_type="kdbx",
            reference=PLACEHOLDER_KDBX_UUID,
            make_home=True,
        )
    except GardenEditError as error:
        raise SnapshotMigrationError(str(error)) from error

    reference = add_entry(
        kdbx_path,
        password_provider,
        title=selection.title,
        username=selection.username,
        url=selection.login,
        value=selection.value,
    )
    try:
        set_prepared_copy_reference(
            prepared,
            alias=selection.alias,
            copy_id=PORTABLE_COPY_ID,
            reference=reference,
        )
        commit_prepared(prepared)
    except GardenEditError as error:
        raise SnapshotMigrationOrphanError(
            alias=selection.alias,
            garden_path=garden_path,
            kdbx_uuid=reference,
        ) from error
    return MigrationResult(selection.alias, reference)
