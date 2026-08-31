"""Device-local Secretariat configuration."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_CONFIG_BYTES = 65_536
MAX_BROWSER_ORIGINS = 16
ROOT_FIELDS = frozenset({"kdbx", "browser"})
KDBX_FIELDS = frozenset({"path"})
BROWSER_FIELDS = frozenset({"allowed_extension_origins"})
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}/$")


class DeviceConfigError(RuntimeError):
    """Bounded machine-configuration failure."""


@dataclass(frozen=True)
class DeviceConfig:
    kdbx_path: Path | None = None
    browser_allowed_extension_origins: tuple[str, ...] = ()


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
    configured_path = path.expanduser()
    document: dict[str, Any] = {}
    if configured_path.exists():
        try:
            if configured_path.stat().st_size > MAX_CONFIG_BYTES:
                raise DeviceConfigError("device config exceeds the reviewed byte limit")
            raw = configured_path.read_bytes()
        except OSError as error:
            raise DeviceConfigError("device config could not be read") from error
        if len(raw) > MAX_CONFIG_BYTES:
            raise DeviceConfigError("device config exceeds the reviewed byte limit")
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DeviceConfigError("device config JSON is invalid") from error
        if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
            raise DeviceConfigError("device config must be a JSON object")
        document = parsed

    if not set(document).issubset(ROOT_FIELDS):
        raise DeviceConfigError("device config contains an unknown field")

    kdbx_path = _parse_kdbx(document.get("kdbx"), configured_path.parent)
    environment_path = os.environ.get("SECRETARIAT_KDBX_PATH")
    if environment_path:
        kdbx_path = _resolved_path(environment_path, Path.cwd())

    browser_origins = _parse_browser(document.get("browser"))
    return DeviceConfig(
        kdbx_path=kdbx_path,
        browser_allowed_extension_origins=browser_origins,
    )


def _parse_kdbx(value: Any, base: Path) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DeviceConfigError("kdbx config must be a JSON object")
    if not set(value).issubset(KDBX_FIELDS):
        raise DeviceConfigError("kdbx config contains an unknown field")
    raw_path: Any = value.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip() or len(raw_path) > 4_096:
        raise DeviceConfigError("kdbx path is invalid")
    return _resolved_path(raw_path, base)


def _parse_browser(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DeviceConfigError("browser config must be a JSON object")
    if not set(value).issubset(BROWSER_FIELDS):
        raise DeviceConfigError("browser config contains an unknown field")
    origins = value.get("allowed_extension_origins", [])
    if not isinstance(origins, list) or len(origins) > MAX_BROWSER_ORIGINS:
        raise DeviceConfigError("browser allowed extension origins are invalid")
    if any(not isinstance(origin, str) or not EXTENSION_ORIGIN.fullmatch(origin) for origin in origins):
        raise DeviceConfigError("browser allowed extension origin is invalid")
    if len(set(origins)) != len(origins):
        raise DeviceConfigError("browser allowed extension origins contain a duplicate")
    return tuple(sorted(origins))


def _resolved_path(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path
