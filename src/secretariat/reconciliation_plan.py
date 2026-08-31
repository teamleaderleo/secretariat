"""Secret-free reviewed reconciliation plans and atomic Garden enrollment."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .garden import GardenError, parse_garden
from .garden_edit import GardenEditError, add_entry_documents
from .reconcile import Group, SNAPSHOT_SOURCES


PLAN_SCHEMA_VERSION = 1
MAX_PLAN_BYTES = 2 * 1024 * 1024
MAX_PLAN_ENTRIES = 2_048
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
PLAN_ROOT_FIELDS = frozenset({"schema_version", "entries"})
PLAN_ENTRY_FIELDS = frozenset({"alias", "title", "username", "provider", "login", "copies", "home"})
PLAN_COPY_FIELDS = frozenset({"id", "type", "reference"})
SOURCE_COPY_IDS = {
    "apple_passwords": "apple",
    "chrome_passwords": "chrome",
    "edge_passwords": "edge",
}


class ReconciliationPlanError(ValueError):
    """Bounded reviewed-plan failure containing metadata only."""


@dataclass(frozen=True)
class PlanCopy:
    id: str
    type: str
    reference: str


@dataclass(frozen=True)
class PlanEntry:
    alias: str
    title: str
    username: str | None
    provider: str
    login: str
    copies: tuple[PlanCopy, ...]
    home: str


@dataclass(frozen=True)
class ReconciliationPlan:
    entries: tuple[PlanEntry, ...]


def plan_template(group: Group) -> dict[str, Any]:
    """Return a secret-free editable template for one reconciliation group."""

    copies = [
        {
            "id": SOURCE_COPY_IDS[source],
            "type": source,
            "reference": snapshot_reference(group.origin, group.username),
        }
        for source in group.sources
    ]
    return {
        "alias": default_alias(group.origin, group.username),
        "title": _safe_plan_title(group.title, group.origin),
        "username": group.username or None,
        "provider": provider_for_origin(group.origin),
        "login": group.origin,
        "copies": copies,
        "home": copies[0]["id"] if len(copies) == 1 else None,
    }


def plan_block_reason(group: Group) -> str | None:
    if group.ambiguous_sources:
        return (
            "Different passwords exist inside one snapshot source: "
            + ", ".join(group.ambiguous_sources)
            + ". Clean that source before enrollment."
        )
    if group.username and not _valid_single_line(group.username, maximum=512):
        return "The snapshot username cannot be represented as Garden account metadata."
    try:
        parsed = urlsplit(group.origin)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return "The normalized login origin is invalid."
    loopback_http = parsed.scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not loopback_http:
        return "Garden enrollment requires HTTPS, except exact HTTP loopback used for generated proofs."
    if not hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return "The normalized login origin cannot be represented as a Garden login link."
    if port is not None and not 0 < port <= 65535:
        return "The normalized login origin has an invalid port."
    return None


def default_alias(origin: str, username: str) -> str:
    try:
        hostname = urlsplit(origin).hostname or "login"
    except ValueError:
        hostname = "login"
    raw = f"{hostname}-{username}" if username else hostname
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._").casefold()
    if not slug or not slug[0].isalnum():
        slug = f"login-{slug}".strip("-")
    if len(slug) <= 72 and TOKEN.fullmatch(slug):
        return slug
    digest = hashlib.sha256(f"{origin}\0{username}".encode("utf-8")).hexdigest()[:12]
    prefix = slug[:72].rstrip("-._") or "login"
    alias = f"{prefix}-{digest}"[:96]
    if not TOKEN.fullmatch(alias):
        return f"login-{digest}"
    return alias


def provider_for_origin(origin: str) -> str:
    try:
        hostname = urlsplit(origin).hostname or "web"
    except ValueError:
        hostname = "web"
    provider = re.sub(r"[^A-Za-z0-9._-]+", "-", hostname).strip("-._").casefold()
    if not provider or not provider[0].isalnum():
        provider = "web"
    if len(provider) > 96:
        digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:12]
        provider = f"web-{digest}"
    return provider if TOKEN.fullmatch(provider) else "web"


def snapshot_reference(origin: str, username: str) -> str:
    rendered = origin if not username else f"{origin} account={username}"
    if len(rendered) <= 512 and _safe_text(rendered, allow_empty=False):
        return rendered
    digest = hashlib.sha256(f"{origin}\0{username}".encode("utf-8")).hexdigest()
    return f"snapshot-metadata-sha256:{digest}"


def load_reconciliation_plan(path: Path) -> ReconciliationPlan:
    target = path.expanduser()
    try:
        if target.is_symlink():
            raise ReconciliationPlanError("reviewed plan path must not be a symbolic link")
        stat = target.stat()
    except OSError as error:
        raise ReconciliationPlanError("reviewed plan could not be inspected") from error
    if not target.is_file():
        raise ReconciliationPlanError("reviewed plan must be a regular file")
    if stat.st_size <= 0 or stat.st_size > MAX_PLAN_BYTES:
        raise ReconciliationPlanError("reviewed plan size is empty or exceeds the reviewed bound")
    try:
        raw = target.read_bytes()
        document = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReconciliationPlanError("reviewed plan is not valid UTF-8 JSON") from error
    return parse_reconciliation_plan(document)


def parse_reconciliation_plan(document: Any) -> ReconciliationPlan:
    root = _object(document, "reviewed plan")
    if set(root) != PLAN_ROOT_FIELDS or root.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ReconciliationPlanError("reviewed plan schema is unsupported")
    raw_entries = root.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries or len(raw_entries) > MAX_PLAN_ENTRIES:
        raise ReconciliationPlanError("reviewed plan entries are invalid or exceed the reviewed bound")
    entries = tuple(_parse_entry(value) for value in raw_entries)
    aliases = [entry.alias for entry in entries]
    if len(set(aliases)) != len(aliases):
        raise ReconciliationPlanError("reviewed plan contains a duplicate credential alias")
    return ReconciliationPlan(entries)


def apply_reconciliation_plan(garden_path: Path, plan_path: Path) -> tuple[str, ...]:
    plan = load_reconciliation_plan(plan_path)
    documents = tuple(_garden_document(entry) for entry in plan.entries)
    try:
        parse_garden({"schema_version": 3, "entries": list(documents)})
        return add_entry_documents(garden_path, documents)
    except GardenError as error:
        raise ReconciliationPlanError(str(error)) from error
    except GardenEditError as error:
        raise ReconciliationPlanError(str(error)) from error


def _parse_entry(value: Any) -> PlanEntry:
    raw = _object(value, "reviewed plan entry")
    if set(raw) != PLAN_ENTRY_FIELDS:
        raise ReconciliationPlanError("reviewed plan entry fields are invalid")
    alias = _token(raw.get("alias"), "reviewed plan alias")
    title = _text(raw.get("title"), "reviewed plan title")
    username = raw.get("username")
    if username is not None:
        username = _single_line_text(username, "reviewed plan username")
    provider = _token(raw.get("provider"), "reviewed plan provider")
    login = _text(raw.get("login"), "reviewed plan login", maximum=2_048)

    raw_copies = raw.get("copies")
    if not isinstance(raw_copies, list) or not raw_copies or len(raw_copies) > len(SNAPSHOT_SOURCES):
        raise ReconciliationPlanError("reviewed plan copies are invalid")
    copies = tuple(_parse_copy(copy) for copy in raw_copies)
    copy_ids = [copy.id for copy in copies]
    if len(set(copy_ids)) != len(copy_ids):
        raise ReconciliationPlanError("reviewed plan contains a duplicate copy id")
    copy_types = [copy.type for copy in copies]
    if len(set(copy_types)) != len(copy_types):
        raise ReconciliationPlanError("reviewed plan must collapse each snapshot source to one copy")

    home = _token(raw.get("home"), "reviewed plan home")
    if home not in copy_ids:
        raise ReconciliationPlanError("reviewed plan home does not name a copy")

    entry = PlanEntry(alias, title, username, provider, login, copies, home)
    try:
        parse_garden({"schema_version": 3, "entries": [_garden_document(entry)]})
    except GardenError as error:
        raise ReconciliationPlanError(str(error)) from error
    return entry


def _parse_copy(value: Any) -> PlanCopy:
    raw = _object(value, "reviewed plan copy")
    if set(raw) != PLAN_COPY_FIELDS:
        raise ReconciliationPlanError("reviewed plan copy fields are invalid")
    copy_id = _token(raw.get("id"), "reviewed plan copy id")
    source_type = raw.get("type")
    if source_type not in SNAPSHOT_SOURCES:
        raise ReconciliationPlanError("reviewed plan copy source is unsupported")
    if SOURCE_COPY_IDS[source_type] != copy_id:
        raise ReconciliationPlanError("reviewed plan copy id does not match its snapshot source")
    reference = _text(raw.get("reference"), "reviewed plan copy reference")
    return PlanCopy(copy_id, source_type, reference)


def _garden_document(entry: PlanEntry) -> dict[str, Any]:
    document: dict[str, Any] = {
        "alias": entry.alias,
        "title": entry.title,
        "kind": "password",
        "provider": entry.provider,
        "copies": [
            {"id": copy.id, "type": copy.type, "reference": copy.reference}
            for copy in entry.copies
        ],
        "home": entry.home,
        "links": {"login": entry.login},
    }
    if entry.username is not None:
        document["username"] = entry.username
    return document


def _safe_plan_title(title: str, origin: str) -> str:
    if len(title) <= 512 and _safe_text(title, allow_empty=False):
        return title
    try:
        hostname = urlsplit(origin).hostname or "Web login"
    except ValueError:
        hostname = "Web login"
    return hostname[:512]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ReconciliationPlanError(f"{label} must be a JSON object")
    return value


def _token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ReconciliationPlanError(f"{label} is invalid")
    return value


def _text(value: Any, label: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or len(value) > maximum or not _safe_text(value, allow_empty=False):
        raise ReconciliationPlanError(f"{label} is invalid")
    return value


def _single_line_text(value: Any, label: str) -> str:
    if not _valid_single_line(value, maximum=512):
        raise ReconciliationPlanError(f"{label} is invalid")
    return value


def _valid_single_line(value: Any, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= maximum
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _safe_text(value: str, *, allow_empty: bool) -> bool:
    if not value and not allow_empty:
        return False
    return not any(ord(character) < 32 and character not in "\n\t" for character in value)
