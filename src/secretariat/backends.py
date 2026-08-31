"""Narrow implemented secret-value and clipboard adapters."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from .garden import Copy


class BackendError(RuntimeError):
    """Bounded backend failure that never contains a credential value."""


@dataclass(frozen=True)
class Tooling:
    secret_tool: str | None
    wl_copy: str | None
    macos_security: str | None

    @classmethod
    def detect(cls) -> "Tooling":
        return cls(
            shutil.which("secret-tool"),
            shutil.which("wl-copy"),
            shutil.which("security"),
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


def backend_for(source: Copy, tooling: Tooling) -> SecretServiceBackend:
    if source.type == "secret_service":
        return SecretServiceBackend(tooling.secret_tool)
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
