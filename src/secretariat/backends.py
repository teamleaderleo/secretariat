"""Narrow implemented secret-value and clipboard adapters."""

from __future__ import annotations

import getpass
import hashlib
import hmac
import importlib.util
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .config import DeviceConfig, DeviceConfigError, default_config_path, load_device_config
from .garden import Copy


class BackendError(RuntimeError):
    """Bounded backend failure that never contains a credential value."""


@dataclass(frozen=True)
class Tooling:
    secret_tool: str | None
    wl_copy: str | None
    macos_security: str | None
    pykeepass_available: bool = False

    @classmethod
    def detect(cls) -> "Tooling":
        return cls(
            shutil.which("secret-tool"),
            shutil.which("wl-copy"),
            shutil.which("security"),
            importlib.util.find_spec("pykeepass") is not None,
        )


class SecretServiceBackend:
    def __init__(self, program: str | None) -> None:
        if program is None:
            raise BackendError("GNOME Secret Service helper is unavailable")
        self._program = program

    def store(self, source: Copy, value: str, label: str) -> None:
        result = subprocess.run(
            [
                self._program,
                "store",
                f"--label=Secretariat: {label}",
                "application",
                "secretariat",
                "reference",
                source.reference,
            ],
            input=value,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise BackendError("credential could not be stored in GNOME Secret Service")

    def load(self, source: Copy) -> str:
        result = subprocess.run(
            [
                self._program,
                "lookup",
                "application",
                "secretariat",
                "reference",
                source.reference,
            ],
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise BackendError("credential could not be retrieved from GNOME Secret Service")
        value = result.stdout.removesuffix("\n")
        if not value:
            raise BackendError("credential is absent from GNOME Secret Service")
        return value


class KDBXBackend:
    """Exact-UUID KDBX access through the optional PyKeePass dependency."""

    def __init__(self, path: Path, password_provider: Callable[[], str] | None) -> None:
        self._path = path.expanduser()
        if password_provider is None:
            raise BackendError("KDBX unlock provider is unavailable")
        self._password_provider = password_provider

    def load(self, source: Copy) -> str:
        database, _baseline = self._open()
        entry = self._entry(database, source)
        value = entry.password
        if not isinstance(value, str) or not value:
            raise BackendError("credential is absent from the KDBX entry")
        return value

    def store(self, source: Copy, value: str, label: str) -> None:
        del label
        database, baseline = self._open()
        entry = self._entry(database, source)
        current = entry.password or ""
        if hmac.compare_digest(current, value):
            return

        entry.save_history()
        entry.password = value
        entry.touch(modify=True)
        _save_database(database, self._path, baseline)

    def _open(self):
        if self._path.is_symlink():
            raise BackendError("KDBX path must not be a symbolic link")
        if not self._path.is_file():
            raise BackendError("KDBX database is unavailable at the configured path")

        try:
            from pykeepass import PyKeePass
        except ImportError as error:
            raise BackendError("KDBX support requires the optional secretariat[kdbx] dependency") from error

        baseline = _encrypted_fingerprint(self._path)
        password = self._password_provider()
        if not isinstance(password, str) or not password:
            raise BackendError("KDBX unlock was cancelled or empty")
        try:
            database = PyKeePass(str(self._path), password=password)
        except Exception as error:
            raise BackendError("KDBX database could not be opened with the supplied unlock credential") from error
        return database, baseline

    @staticmethod
    def _entry(database, source: Copy):
        if len(source.reference) != 32 or any(
            character not in "0123456789abcdef" for character in source.reference
        ):
            raise BackendError("KDBX copy reference must be a canonical lowercase 32-hex entry UUID")
        try:
            entry_uuid = uuid.UUID(hex=source.reference)
        except ValueError as error:
            raise BackendError("KDBX copy reference must be a canonical lowercase 32-hex entry UUID") from error
        try:
            matches = database.find_entries(uuid=entry_uuid, first=False)
        except Exception as error:
            raise BackendError("KDBX entry lookup failed") from error
        if len(matches) == 0:
            raise BackendError("KDBX entry UUID was not found")
        if len(matches) != 1:
            raise BackendError("KDBX entry UUID resolved to multiple entries")
        return matches[0]


def create_kdbx_home(path: Path, password: str) -> None:
    """Create a new encrypted KDBX home at an unused configured path."""
    target = path.expanduser()
    if not isinstance(password, str) or not password:
        raise BackendError("KDBX master password was empty")
    if target.exists() or target.is_symlink():
        raise BackendError("KDBX home already exists at the configured path")
    if not target.parent.is_dir():
        raise BackendError("KDBX home parent directory is unavailable")

    try:
        from pykeepass import create_database
    except ImportError as error:
        raise BackendError("KDBX support requires the optional secretariat[kdbx] dependency") from error

    temporary = _temporary_path(target)
    try:
        try:
            temporary.unlink()
            create_database(str(temporary), password=password)
            os.chmod(temporary, 0o600)
            _fsync_file(temporary)
        except Exception as error:
            raise BackendError("KDBX home could not be created") from error
        if target.exists() or target.is_symlink():
            raise BackendError("KDBX home appeared during creation; refusing to replace it")
        try:
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        except OSError as error:
            raise BackendError("KDBX home could not be installed atomically") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def add_kdbx_entry(
    path: Path,
    password_provider: Callable[[], str],
    *,
    title: str,
    username: str,
    url: str | None,
    value: str,
) -> str:
    """Add one secret value to the existing home and return its stable UUID."""
    if not value:
        raise BackendError("credential value was empty")
    backend = KDBXBackend(path, password_provider)
    database, baseline = backend._open()
    try:
        entry = database.add_entry(
            database.root_group,
            title,
            username,
            value,
            url=url or None,
        )
    except Exception as error:
        raise BackendError("KDBX entry could not be created") from error
    _save_database(database, backend._path, baseline)
    return entry.uuid.hex.lower()


def backend_for(
    source: Copy,
    tooling: Tooling,
    *,
    device_config: DeviceConfig | None = None,
    password_provider: Callable[[], str] | None = None,
):
    if source.type == "secret_service":
        return SecretServiceBackend(tooling.secret_tool)
    if source.type == "kdbx":
        if not tooling.pykeepass_available:
            raise BackendError("KDBX support requires the optional secretariat[kdbx] dependency")
        if device_config is None:
            try:
                device_config = load_device_config(default_config_path())
            except DeviceConfigError as error:
                raise BackendError(str(error)) from error
        if device_config.kdbx_path is None:
            raise BackendError("KDBX home path is not configured on this device")
        if password_provider is None:
            password_provider = lambda: getpass.getpass("KDBX master password: ")
        return KDBXBackend(device_config.kdbx_path, password_provider)
    raise BackendError(f"{source.type} is indexed only; value access is unavailable")


def copy_paste_once(value: str, tooling: Tooling) -> None:
    if tooling.wl_copy is None:
        raise BackendError("paste-once Wayland clipboard helper is unavailable")
    result = subprocess.run(
        [tooling.wl_copy, "--paste-once", "--trim-newline"],
        input=value,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise BackendError("credential could not be placed on the paste-once clipboard")


def _save_database(database, path: Path, baseline: tuple[int, int, bytes]) -> None:
    if _encrypted_fingerprint(path) != baseline:
        raise BackendError("KDBX home diverged before save; review the competing revision")

    temporary = _temporary_path(path)
    try:
        try:
            database.save(str(temporary))
            os.chmod(temporary, 0o600)
            _fsync_file(temporary)
        except Exception as error:
            raise BackendError("KDBX database could not be saved") from error

        if _encrypted_fingerprint(path) != baseline:
            raise BackendError("KDBX home diverged during save; review the competing revision")
        try:
            os.replace(temporary, path)
            _fsync_directory(path.parent)
        except OSError as error:
            raise BackendError("KDBX database could not be replaced atomically") from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _encrypted_fingerprint(path: Path) -> tuple[int, int, bytes]:
    try:
        before = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.stat()
    except OSError as error:
        raise BackendError("KDBX database could not be inspected") from error
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise BackendError("KDBX database changed while being inspected")
    return after.st_size, after.st_mtime_ns, digest.digest()


def _temporary_path(path: Path) -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{path.name}.secretariat-",
            suffix=".tmp",
            dir=path.parent,
        )
        os.close(descriptor)
        os.chmod(raw_path, 0o600)
    except OSError as error:
        raise BackendError("KDBX temporary file could not be created") from error
    return Path(raw_path)


def _fsync_file(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError as error:
        raise BackendError("KDBX temporary file could not be flushed") from error


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
