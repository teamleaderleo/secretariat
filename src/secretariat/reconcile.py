"""Read-only reconciliation of temporary password-manager snapshots."""

from __future__ import annotations

import csv
import hmac
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOT_ROWS = 20_000
SNAPSHOT_SOURCES = frozenset({"chrome_passwords", "edge_passwords", "apple_passwords"})


class ReconcileError(ValueError):
    """Bounded reconciliation failure that never includes credential values."""


@dataclass(frozen=True)
class SnapshotSpec:
    source: str
    path: Path


@dataclass(frozen=True)
class Observation:
    source: str
    row: int
    title: str
    url: str
    username: str
    password: str
    notes: str
    otp_auth: str

    @property
    def origin(self) -> str:
        return normalize_origin(self.url)

    @property
    def username_key(self) -> str:
        return self.username.strip().casefold()


@dataclass(frozen=True)
class Group:
    origin: str
    username: str
    classification: str
    copies: int
    sources: tuple[str, ...]
    source_counts: tuple[tuple[str, int], ...]
    note_sources: tuple[str, ...]
    otp_sources: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    snapshot_count: int
    observation_count: int
    groups: tuple[Group, ...]
    multi_account_origins: tuple[str, ...]

    def counts(self) -> dict[str, int]:
        values = Counter(group.classification for group in self.groups)
        return {
            "single": values["single"],
            "duplicate": values["duplicate"],
            "conflict": values["conflict"],
            "multi_account_origins": len(self.multi_account_origins),
        }


def parse_snapshot_spec(value: str) -> SnapshotSpec:
    source, separator, raw_path = value.partition("=")
    if not separator or not source or not raw_path:
        raise ReconcileError("snapshot must use SOURCE=PATH")
    if source not in SNAPSHOT_SOURCES:
        raise ReconcileError("snapshot source is unsupported")
    return SnapshotSpec(source=source, path=Path(raw_path).expanduser())


def read_snapshot(spec: SnapshotSpec) -> tuple[Observation, ...]:
    path = spec.path
    try:
        if path.is_symlink():
            raise ReconcileError("snapshot path must not be a symbolic link")
        stat = path.stat()
    except OSError as error:
        raise ReconcileError("snapshot could not be inspected") from error
    if not path.is_file():
        raise ReconcileError("snapshot path must be a regular file")
    if stat.st_size <= 0 or stat.st_size > MAX_SNAPSHOT_BYTES:
        raise ReconcileError("snapshot size is empty or exceeds the reviewed bound")

    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as error:
        raise ReconcileError("snapshot could not be opened") from error

    observations: list[Observation] = []
    try:
        with handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ReconcileError("snapshot is missing a CSV header")
            fields = _field_map(reader.fieldnames)
            required = {"url", "username", "password"}
            if not required.issubset(fields):
                raise ReconcileError("snapshot requires url, username, and password columns")
            for row_number, row in enumerate(reader, start=2):
                if len(observations) >= MAX_SNAPSHOT_ROWS:
                    raise ReconcileError("snapshot exceeds the reviewed row bound")
                try:
                    url = _row_value(row, fields["url"])
                    username = _row_value(row, fields["username"])
                    password = _row_value(row, fields["password"])
                    title = _optional_row_value(row, fields.get("title"))
                    notes = _optional_row_value(row, fields.get("notes"))
                    otp_auth = _optional_row_value(row, fields.get("otp_auth"))
                except (TypeError, AttributeError) as error:
                    raise ReconcileError(f"snapshot row {row_number} is malformed") from error
                if not url.strip():
                    raise ReconcileError(f"snapshot row {row_number} has an empty URL")
                observations.append(
                    Observation(
                        source=spec.source,
                        row=row_number,
                        title=title.strip(),
                        url=url.strip(),
                        username=username.strip(),
                        password=password,
                        notes=notes,
                        otp_auth=otp_auth,
                    )
                )
    except UnicodeDecodeError as error:
        raise ReconcileError("snapshot must be UTF-8 CSV") from error
    except csv.Error as error:
        raise ReconcileError("snapshot CSV is malformed") from error
    return tuple(observations)


def reconcile(specs: tuple[SnapshotSpec, ...]) -> Report:
    if not specs:
        raise ReconcileError("reconcile requires at least one snapshot")
    observations = tuple(observation for spec in specs for observation in read_snapshot(spec))

    grouped: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    origin_accounts: dict[str, set[str]] = defaultdict(set)
    display_usernames: dict[tuple[str, str], str] = {}
    for observation in observations:
        key = (observation.origin, observation.username_key)
        grouped[key].append(observation)
        origin_accounts[observation.origin].add(observation.username_key)
        display_usernames.setdefault(key, observation.username)

    groups = []
    for key, members in sorted(grouped.items()):
        origin, _username_key = key
        classification = _classify(tuple(members))
        source_counts = tuple(sorted(Counter(member.source for member in members).items()))
        groups.append(
            Group(
                origin=origin,
                username=display_usernames[key],
                classification=classification,
                copies=len(members),
                sources=tuple(source for source, _count in source_counts),
                source_counts=source_counts,
                note_sources=tuple(sorted({member.source for member in members if member.notes})),
                otp_sources=tuple(sorted({member.source for member in members if member.otp_auth})),
            )
        )

    multi_account_origins = tuple(
        sorted(origin for origin, accounts in origin_accounts.items() if len(accounts) > 1)
    )
    return Report(
        snapshot_count=len(specs),
        observation_count=len(observations),
        groups=tuple(groups),
        multi_account_origins=multi_account_origins,
    )


def normalize_origin(raw_url: str) -> str:
    value = raw_url.strip()
    if not value:
        raise ReconcileError("snapshot contains an empty URL")
    candidate = value if "://" in value else f"https://{value}"
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ReconcileError("snapshot contains an invalid URL") from error

    if not parsed.scheme or not hostname:
        return value.casefold()

    scheme = parsed.scheme.casefold()
    host = hostname.rstrip(".").casefold()
    if not host:
        return value.casefold()

    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{authority}"


def _classify(members: tuple[Observation, ...]) -> str:
    if len(members) == 1:
        return "single"
    first = members[0].password
    if all(hmac.compare_digest(first, member.password) for member in members[1:]):
        return "duplicate"
    return "conflict"


def _field_map(fieldnames: list[str]) -> dict[str, str]:
    aliases = {
        "url": {"url", "website", "website address", "login_uri"},
        "username": {"username", "user", "login", "login_username"},
        "password": {"password", "pwd", "login_password"},
        "title": {"title", "name"},
        "notes": {"notes", "note", "extra"},
        "otp_auth": {"otpauth", "otp_auth"},
    }
    normalized = {name.strip().casefold(): name for name in fieldnames if isinstance(name, str)}
    result: dict[str, str] = {}
    for canonical, choices in aliases.items():
        for choice in choices:
            if choice in normalized:
                result[canonical] = normalized[choice]
                break
    return result


def _row_value(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    return "" if value is None else str(value)


def _optional_row_value(row: dict[str, str | None], field: str | None) -> str:
    return "" if field is None else _row_value(row, field)
