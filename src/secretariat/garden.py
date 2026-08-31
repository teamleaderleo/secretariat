"""Strict secret-free Garden model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 3
MAX_GARDEN_BYTES = 1_048_576
MAX_ENTRIES = 2_048
MAX_TEXT = 512
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
KDBX_ENTRY_UUID = re.compile(r"^[0-9a-f]{32}$")

ROOT_FIELDS = frozenset({"schema_version", "entries"})
ENTRY_FIELDS = frozenset(
    {
        "alias",
        "title",
        "username",
        "kind",
        "provider",
        "purpose",
        "environment",
        "status",
        "scopes",
        "copies",
        "home",
        "delivery",
        "created_at",
        "expires_at",
        "rotate_by",
        "last_tested_at",
        "public_fingerprint",
        "links",
        "notes",
    }
)
ENTRY_REQUIRED = frozenset({"alias", "title", "kind", "provider", "copies"})
COPY_FIELDS = frozenset({"id", "type", "reference"})
COPY_REQUIRED = COPY_FIELDS
DELIVERY_FIELDS = frozenset({"type", "name"})
DELIVERY_REQUIRED = DELIVERY_FIELDS
LINK_FIELDS = frozenset({"manage", "revoke", "docs", "login"})
STATUSES = frozenset({"active", "rotating", "revoked", "retired", "unknown"})
KINDS = frozenset(
    {
        "account",
        "api_token",
        "oauth_token",
        "password",
        "passkey",
        "ssh_key",
        "recovery_codes",
        "totp",
        "service_credential",
        "other",
    }
)
SOURCE_TYPES = frozenset(
    {
        "secret_service",
        "macos_keychain",
        "apple_passwords",
        "chrome_passwords",
        "edge_passwords",
        "ssh_agent",
        "kdbx",
        "external",
    }
)
DELIVERY_TYPES = frozenset({"env"})
FORBIDDEN_FIELD_FRAGMENTS = (
    "password_value",
    "secret_value",
    "token_value",
    "private_key",
    "recovery_code_value",
    "totp_seed",
    "authorization_header",
    "cookie_value",
)


class GardenError(ValueError):
    """Bounded Garden failure that never includes source values."""


@dataclass(frozen=True)
class Copy:
    id: str
    type: str
    reference: str


@dataclass(frozen=True)
class Delivery:
    type: str
    name: str


@dataclass(frozen=True)
class Entry:
    alias: str
    title: str
    username: str | None
    kind: str
    provider: str
    purpose: str
    environment: str
    status: str
    scopes: tuple[str, ...]
    copies: tuple[Copy, ...]
    home: str | None
    delivery: Delivery | None
    created_at: date | None
    expires_at: date | None
    rotate_by: date | None
    last_tested_at: date | None
    public_fingerprint: str | None
    links: dict[str, str]
    notes: str

    def due_on(self) -> date | None:
        dates = [value for value in (self.rotate_by, self.expires_at) if value is not None]
        return min(dates) if dates else None

    def copy_by_id(self, copy_id: str) -> Copy:
        for copy in self.copies:
            if copy.id == copy_id:
                return copy
        raise GardenError("credential copy id was not found")

    def home_copy(self) -> Copy:
        if self.home is not None:
            return self.copy_by_id(self.home)
        if len(self.copies) == 1:
            return self.copies[0]
        raise GardenError("credential with multiple copies has no home")

    def search_text(self) -> str:
        values = [
            self.alias,
            self.title,
            self.username or "",
            self.kind,
            self.provider,
            self.purpose,
            self.environment,
            self.status,
            self.public_fingerprint or "",
            self.notes,
            *self.scopes,
        ]
        for copy in self.copies:
            values.extend((copy.id, copy.type, copy.reference))
        return "\n".join(values).casefold()


@dataclass(frozen=True)
class Garden:
    entries: tuple[Entry, ...]

    def by_alias(self, alias: str) -> Entry:
        for entry in self.entries:
            if entry.alias == alias:
                return entry
        raise GardenError("credential alias was not found")

    def find(self, query: str) -> tuple[Entry, ...]:
        terms = tuple(term.casefold() for term in query.split() if term)
        if not terms:
            raise GardenError("find query must contain text")
        return tuple(entry for entry in self.entries if all(term in entry.search_text() for term in terms))


def load_garden(path: Path) -> Garden:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise GardenError("Garden could not be inspected") from error
    if size > MAX_GARDEN_BYTES:
        raise GardenError("Garden exceeds the reviewed byte limit")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise GardenError("Garden could not be read") from error
    if len(raw) > MAX_GARDEN_BYTES:
        raise GardenError("Garden exceeds the reviewed byte limit")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GardenError("Garden JSON is invalid") from error
    return parse_garden(document)


def parse_garden(document: Any) -> Garden:
    root = _object(document, "Garden")
    _fields(root, ROOT_FIELDS, ROOT_FIELDS, "Garden")
    if root["schema_version"] != SCHEMA_VERSION:
        raise GardenError("Garden schema version is unsupported")
    raw_entries = root["entries"]
    if not isinstance(raw_entries, list) or len(raw_entries) > MAX_ENTRIES:
        raise GardenError("Garden entries are invalid or exceed the reviewed bound")
    entries = tuple(_parse_entry(value) for value in raw_entries)
    aliases = {entry.alias for entry in entries}
    if len(aliases) != len(entries):
        raise GardenError("Garden contains a duplicate credential alias")
    return Garden(tuple(sorted(entries, key=lambda entry: entry.alias)))


def _parse_entry(value: Any) -> Entry:
    raw = _object(value, "entry")
    _fields(raw, ENTRY_FIELDS, ENTRY_REQUIRED, "entry")

    copies_raw = raw["copies"]
    if not isinstance(copies_raw, list) or not copies_raw or len(copies_raw) > 32:
        raise GardenError("credential copies are invalid or exceed the reviewed bound")
    copies = tuple(_parse_copy(copy_raw) for copy_raw in copies_raw)
    copy_ids = {copy.id for copy in copies}
    if len(copy_ids) != len(copies):
        raise GardenError("credential contains a duplicate copy id")

    home = raw.get("home")
    if home is not None:
        home = _token(home, "home copy id")
        if home not in copy_ids:
            raise GardenError("home copy id does not name a credential copy")
    elif len(copies) > 1:
        raise GardenError("credential with multiple copies requires a home copy id")

    delivery = None
    delivery_raw = raw.get("delivery")
    if delivery_raw is not None:
        delivery_object = _object(delivery_raw, "delivery")
        _fields(delivery_object, DELIVERY_FIELDS, DELIVERY_REQUIRED, "delivery")
        delivery_type = _choice(delivery_object["type"], DELIVERY_TYPES, "delivery type")
        delivery_name = delivery_object["name"]
        if delivery_type == "env":
            if not isinstance(delivery_name, str) or not ENV_NAME.fullmatch(delivery_name):
                raise GardenError("environment delivery name is invalid")
        delivery = Delivery(delivery_type, delivery_name)

    scopes_raw = raw.get("scopes", [])
    if (
        not isinstance(scopes_raw, list)
        or len(scopes_raw) > 64
        or any(not isinstance(scope, str) or not scope or len(scope) > 128 for scope in scopes_raw)
        or len(set(scopes_raw)) != len(scopes_raw)
    ):
        raise GardenError("credential scopes are invalid")

    links_raw = _object(raw.get("links", {}), "links")
    if not set(links_raw).issubset(LINK_FIELDS):
        raise GardenError("links contain an unknown field")
    links: dict[str, str] = {}
    for label, url in links_raw.items():
        if not isinstance(url, str) or len(url) > 2_048:
            raise GardenError("credential link is invalid")
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise GardenError("credential links must be credential-free HTTPS URLs")
        links[label] = url

    return Entry(
        alias=_token(raw["alias"], "alias"),
        title=_text(raw["title"], "title"),
        username=_optional_single_line_text(raw.get("username"), "username"),
        kind=_choice(raw["kind"], KINDS, "kind"),
        provider=_token(raw["provider"], "provider"),
        purpose=_text(raw.get("purpose", ""), "purpose", allow_empty=True),
        environment=_token(raw.get("environment", "personal"), "environment"),
        status=_choice(raw.get("status", "active"), STATUSES, "status"),
        scopes=tuple(sorted(scopes_raw)),
        copies=copies,
        home=home,
        delivery=delivery,
        created_at=_date_or_none(raw.get("created_at"), "created_at"),
        expires_at=_date_or_none(raw.get("expires_at"), "expires_at"),
        rotate_by=_date_or_none(raw.get("rotate_by"), "rotate_by"),
        last_tested_at=_date_or_none(raw.get("last_tested_at"), "last_tested_at"),
        public_fingerprint=_optional_text(raw.get("public_fingerprint"), "public fingerprint"),
        links=links,
        notes=_text(raw.get("notes", ""), "notes", allow_empty=True),
    )


def _parse_copy(value: Any) -> Copy:
    raw = _object(value, "copy")
    _fields(raw, COPY_FIELDS, COPY_REQUIRED, "copy")
    source_type = _choice(raw["type"], SOURCE_TYPES, "copy source type")
    reference = _text(raw["reference"], "copy reference")
    if source_type == "kdbx" and not KDBX_ENTRY_UUID.fullmatch(reference):
        raise GardenError("KDBX copy reference must be a canonical lowercase 32-hex entry UUID")
    return Copy(
        id=_token(raw["id"], "copy id"),
        type=source_type,
        reference=reference,
    )


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise GardenError(f"{label} must be a JSON object")
    for key in value:
        normalized = key.lower()
        if any(fragment in normalized for fragment in FORBIDDEN_FIELD_FRAGMENTS):
            raise GardenError(f"{label} contains a forbidden value-bearing field")
    return value


def _fields(
    value: dict[str, Any],
    allowed: frozenset[str],
    required: frozenset[str],
    label: str,
) -> None:
    keys = set(value)
    if not keys.issubset(allowed):
        raise GardenError(f"{label} contains an unknown field")
    if not required.issubset(keys):
        raise GardenError(f"{label} is missing a required field")


def _token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise GardenError(f"{label} is invalid")
    return value


def _choice(value: Any, choices: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise GardenError(f"{label} is unsupported")
    return value


def _text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_TEXT
        or (not allow_empty and not value)
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise GardenError(f"{label} is invalid")
    return value


def _optional_text(value: Any, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _optional_single_line_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_TEXT
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise GardenError(f"{label} is invalid")
    return value


def _date_or_none(value: Any, label: str) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GardenError(f"{label} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise GardenError(f"{label} is invalid") from error
