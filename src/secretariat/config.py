"""Device-local Secretariat configuration."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_CONFIG_BYTES = 65_536
ROOT_FIELDS = frozenset({"kdbx"})
KDBX_FIELDS = frozenset({"path"})


class DeviceConfigError(RuntimeError):
    """Bounded machine-configuration failure."""


@dataclass(frozen=True)
class DeviceConfig:
    kdbx_path: Path | None = None


def default_config_path() -> Path:
    configured = os.environ.get("SECRETARIAT_CONFIG")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Secretariat" / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "secretariat" / "config.json"


def load_device_config(path: Path) -> DeviceConfig:
    environment_path = os.environ.get("SECRETARIAT_KDBX_PATH")
    if environment_path:
        return DeviceConfig(kdbx_path=_resolved_path(environment_path, Path.cwd()))

    configured_path = path.expanduser()
    if not configured_path.exists():
        return DeviceConfig()
    try:
        if configured_path.stat().st_size > MAX_CONFIG_BYTES:
            raise DeviceConfigError("device config exceeds the reviewed byte limit")
        raw = configured_path.read_bytes()
    except OSError as error:
        raise DeviceConfigError("device config could not be read") from error
    if len(raw) > MAX_CONFIG_BYTES:
        raise DeviceConfigError("device config exceeds the reviewed byte limit")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DeviceConfigError("device config JSON is invalid") from error
    if not isinstance(document, dict) or any(not isinstance(key, str) for key in document):
        raise DeviceConfigError("device config must be a JSON object")
    if not set(document).issubset(ROOT_FIELDS):
        raise DeviceConfigError("device config contains an unknown field")

    kdbx = document.get("kdbx")
    if kdbx is None:
        return DeviceConfig()
    if not isinstance(kdbx, dict) or any(not isinstance(key, str) for key in kdbx):
        raise DeviceConfigError("kdbx config must be a JSON object")
    if not set(kdbx).issubset(KDBX_FIELDS):
        raise DeviceConfigError("kdbx config contains an unknown field")
    raw_path: Any = kdbx.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip() or len(raw_path) > 4_096:
        raise DeviceConfigError("kdbx path is invalid")
    return DeviceConfig(kdbx_path=_resolved_path(raw_path, configured_path.parent))


def _resolved_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path
