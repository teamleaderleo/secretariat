"""Atomic edits for the private, secret-free Garden file."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .garden import MAX_GARDEN_BYTES, GardenError, parse_garden


class GardenEditError(RuntimeError):
    """Bounded Garden mutation failure."""


@dataclass(frozen=True)
class GardenFile:
    path: Path
    document: dict[str, Any]
    fingerprint: tuple[int, int, bytes]


def add_entry(
    path: Path,
    *,
    alias: str,
    title: str,
    kind: str,
    provider: str,
    copy_id: str,
    copy_type: str,
    reference: str,
) -> None:
    garden_file = _read(path)
    entries = garden_file.document["entries"]
    if any(entry.get("alias") == alias for entry in entries):
        raise GardenEditError("Garden already contains that credential alias")
    entries.append(
        {
            "alias": alias,
            "title": title,
            "kind": kind,
            "provider": provider,
            "copies": [
                {
                    "id": copy_id,
                    "type": copy_type,
                    "reference": reference,
                }
            ],
            "home": copy_id,
        }
    )
    _write(garden_file)


def attach_copy(
    path: Path,
    *,
    alias: str,
    copy_id: str,
    copy_type: str,
    reference: str,
    make_home: bool,
) -> None:
    garden_file = _read(path)
    entry = _entry(garden_file.document, alias)
    copies = entry["copies"]
    if any(copy.get("id") == copy_id for copy in copies):
        raise GardenEditError("credential already contains that copy id")

    if len(copies) == 1 and "home" not in entry:
        entry["home"] = copies[0]["id"]
    copies.append({"id": copy_id, "type": copy_type, "reference": reference})
    if make_home:
        entry["home"] = copy_id
    _write(garden_file)


def set_home(path: Path, *, alias: str, copy_id: str) -> None:
    garden_file = _read(path)
    entry = _entry(garden_file.document, alias)
    if not any(copy.get("id") == copy_id for copy in entry["copies"]):
        raise GardenEditError("home copy id does not name a credential copy")
    entry["home"] = copy_id
    _write(garden_file)


def set_login(path: Path, *, alias: str, url: str) -> None:
    garden_file = _read(path)
    entry = _entry(garden_file.document, alias)
    links = entry.get("links")
    if links is None:
        links = {}
        entry["links"] = links
    if not isinstance(links, dict):
        raise GardenEditError("credential links are invalid")
    links["login"] = url
    _write(garden_file)


def detach_copy(
    path: Path,
    *,
    alias: str,
    copy_id: str,
    new_home: str | None,
) -> None:
    garden_file = _read(path)
    entry = _entry(garden_file.document, alias)
    copies = entry["copies"]
    matching = [copy for copy in copies if copy.get("id") == copy_id]
    if len(matching) != 1:
        raise GardenEditError("credential copy id was not found")
    if len(copies) == 1:
        raise GardenEditError("cannot detach the only credential copy")

    current_home = entry.get("home") or copies[0]["id"]
    remaining_ids = {copy["id"] for copy in copies if copy.get("id") != copy_id}
    if new_home is not None and new_home not in remaining_ids:
        raise GardenEditError("new home must name a remaining credential copy")
    if current_home == copy_id and new_home is None:
        raise GardenEditError("detaching the home copy requires --new-home")

    entry["copies"] = [copy for copy in copies if copy.get("id") != copy_id]
    if new_home is not None:
        entry["home"] = new_home
    elif entry.get("home") == copy_id:
        raise GardenEditError("credential home would become invalid")
    _write(garden_file)


def _read(path: Path) -> GardenFile:
    target = path.expanduser()
    if target.is_symlink():
        raise GardenEditError("Garden path must not be a symbolic link")
    if not target.is_file():
        raise GardenEditError("Garden file is unavailable")
    try:
        before = target.stat()
        if before.st_size > MAX_GARDEN_BYTES:
            raise GardenEditError("Garden exceeds the reviewed byte limit")
        raw = target.read_bytes()
        after = target.stat()
    except OSError as error:
        raise GardenEditError("Garden could not be read") from error
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise GardenEditError("Garden changed while being read")
    if len(raw) > MAX_GARDEN_BYTES:
        raise GardenEditError("Garden exceeds the reviewed byte limit")
    try:
        document = json.loads(raw)
        parse_garden(document)
    except (UnicodeDecodeError, json.JSONDecodeError, GardenError) as error:
        raise GardenEditError("Garden is invalid and cannot be edited") from error
    if not isinstance(document, dict):
        raise GardenEditError("Garden must be a JSON object")
    return GardenFile(
        path=target,
        document=document,
        fingerprint=(after.st_size, after.st_mtime_ns, hashlib.sha256(raw).digest()),
    )


def _write(garden_file: GardenFile) -> None:
    try:
        parse_garden(garden_file.document)
    except GardenError as error:
        raise GardenEditError(str(error)) from error
    payload = (json.dumps(garden_file.document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(payload) > MAX_GARDEN_BYTES:
        raise GardenEditError("edited Garden exceeds the reviewed byte limit")
    if _fingerprint(garden_file.path) != garden_file.fingerprint:
        raise GardenEditError("Garden diverged before save; review the competing revision")

    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{garden_file.path.name}.secretariat-",
            suffix=".tmp",
            dir=garden_file.path.parent,
        )
        temporary = Path(raw_path)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        raise GardenEditError("Garden temporary file could not be written") from error

    try:
        if _fingerprint(garden_file.path) != garden_file.fingerprint:
            raise GardenEditError("Garden diverged during save; review the competing revision")
        os.replace(temporary, garden_file.path)
        _fsync_directory(garden_file.path.parent)
    except OSError as error:
        raise GardenEditError("Garden could not be replaced atomically") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _fingerprint(path: Path) -> tuple[int, int, bytes]:
    try:
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
    except OSError as error:
        raise GardenEditError("Garden could not be inspected") from error
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise GardenEditError("Garden changed while being inspected")
    return after.st_size, after.st_mtime_ns, hashlib.sha256(raw).digest()


def _entry(document: dict[str, Any], alias: str) -> dict[str, Any]:
    matches = [entry for entry in document["entries"] if entry.get("alias") == alias]
    if len(matches) != 1:
        raise GardenEditError("credential alias was not found")
    return matches[0]


def _fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
