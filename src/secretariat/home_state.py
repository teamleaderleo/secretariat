"""Value-free portable KDBX home and unlock-agent status."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backends import Tooling
from .config import DeviceConfig
from .kdbx_agent import KDBXAgentClient, KDBXAgentError


@dataclass(frozen=True)
class PortableHomeStatus:
    state: str
    kdbx_library: str
    kdbx_path: str
    kdbx_file: str
    agent: str
    idle_seconds_remaining: int | None = None
    ttl_seconds_remaining: int | None = None

    def as_dict(self) -> dict[str, str | int | None]:
        return {
            "state": self.state,
            "kdbx_library": self.kdbx_library,
            "kdbx_path": self.kdbx_path,
            "kdbx_file": self.kdbx_file,
            "agent": self.agent,
            "idle_seconds_remaining": self.idle_seconds_remaining,
            "ttl_seconds_remaining": self.ttl_seconds_remaining,
        }


def inspect_portable_home(
    tooling: Tooling,
    config: DeviceConfig,
    *,
    agent: KDBXAgentClient | None = None,
) -> PortableHomeStatus:
    if not tooling.pykeepass_available:
        return PortableHomeStatus(
            state="dependency_missing",
            kdbx_library="missing",
            kdbx_path="configured" if config.kdbx_path is not None else "missing",
            kdbx_file=_file_state(config.kdbx_path),
            agent="not_checked",
        )
    if config.kdbx_path is None:
        return PortableHomeStatus(
            state="config_missing",
            kdbx_library="available",
            kdbx_path="missing",
            kdbx_file="missing",
            agent="not_checked",
        )
    if not config.kdbx_path.is_file():
        return PortableHomeStatus(
            state="file_missing",
            kdbx_library="available",
            kdbx_path="configured",
            kdbx_file="missing",
            agent="not_checked",
        )

    client = agent or KDBXAgentClient()
    try:
        response = client.request("status")
    except KDBXAgentError as error:
        if error.code == "unsupported_platform":
            agent_state = "unsupported"
            overall = "available_locked"
        elif error.code in {"agent_unavailable", "locked"}:
            agent_state = "locked"
            overall = "available_locked"
        elif error.code == "backend_failure":
            agent_state = "invalidated"
            overall = "changed_since_unlock"
        elif error.code in {"socket_path", "runtime_directory"}:
            agent_state = "unsafe_endpoint"
            overall = "agent_unsafe"
        else:
            agent_state = "unavailable"
            overall = "agent_unavailable"
        return PortableHomeStatus(
            state=overall,
            kdbx_library="available",
            kdbx_path="configured",
            kdbx_file="available",
            agent=agent_state,
        )

    idle = response.get("idle_seconds_remaining")
    ttl = response.get("ttl_seconds_remaining")
    return PortableHomeStatus(
        state="available_unlocked",
        kdbx_library="available",
        kdbx_path="configured",
        kdbx_file="available",
        agent="unlocked",
        idle_seconds_remaining=idle if isinstance(idle, int) and idle >= 0 else None,
        ttl_seconds_remaining=ttl if isinstance(ttl, int) and ttl >= 0 else None,
    )


def _file_state(path: Path | None) -> str:
    return "available" if path is not None and path.is_file() else "missing"
