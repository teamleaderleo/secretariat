"""Chrome/Edge native messaging host for explicit Secretariat browser actions."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, BinaryIO

from .backends import BackendError, Tooling, backend_for
from .browser_protocol import (
    MAX_MESSAGE_BYTES,
    BrowserProtocolError,
    BrowserRequest,
    canonical_origin,
    error_response,
    ok_response,
    parse_request,
)
from .config import DeviceConfigError, default_config_path, load_device_config
from .garden import Copy, Entry, Garden, GardenError, load_garden
from .kdbx_agent import KDBXAgentClient, KDBXAgentError


class NativeHostError(RuntimeError):
    """Bounded native-host failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BrowserBroker:
    def __init__(
        self,
        garden: Garden,
        tooling: Tooling,
        *,
        kdbx_agent: KDBXAgentClient | None = None,
    ) -> None:
        self._garden = garden
        self._tooling = tooling
        self._kdbx_agent = kdbx_agent or KDBXAgentClient()

    def handle(self, request: BrowserRequest) -> dict[str, Any]:
        kdbx_available = self._kdbx_agent_available()
        if request.action == "status":
            secret_service_available = self._tooling.secret_tool is not None
            sources = []
            if secret_service_available:
                sources.append("secret_service")
            if kdbx_available:
                sources.append("kdbx")
            return ok_response(
                request.request_id,
                capabilities={
                    "match": True,
                    "get": bool(sources),
                    "get_sources": sources,
                    "update": bool(sources),
                    "update_sources": sources,
                },
            )

        if request.origin is None:
            raise NativeHostError("invalid_origin", "page origin is required")

        if request.action == "match":
            matches = tuple(entry for entry in self._garden.entries if _entry_matches_origin(entry, request.origin))
            return ok_response(
                request.request_id,
                credentials=[
                    _credential_view(entry, self._tooling, kdbx_available=kdbx_available)
                    for entry in matches
                    if entry.kind == "password"
                ],
            )

        if request.action == "get":
            entry, home = self._authorized_password_entry(request, kdbx_available=kdbx_available)
            try:
                if home.type == "kdbx":
                    password = self._kdbx_agent.load(home)
                else:
                    password = backend_for(home, self._tooling).load(home)
            except (BackendError, KDBXAgentError) as error:
                raise NativeHostError("backend_unavailable", "credential could not be retrieved") from error
            return ok_response(request.request_id, username=entry.username, password=password)

        if request.action == "update":
            entry, home = self._authorized_password_entry(request, kdbx_available=kdbx_available)
            if request.password is None:
                raise NativeHostError("invalid_password", "password value is required")
            try:
                if home.type == "kdbx":
                    self._kdbx_agent.store(home, request.password)
                else:
                    backend_for(home, self._tooling).store(home, request.password, entry.title)
            except (BackendError, KDBXAgentError) as error:
                raise NativeHostError("backend_unavailable", "credential could not be updated") from error
            return ok_response(request.request_id, updated=True)

        raise NativeHostError("unsupported_action", "request action is unsupported")

    def _authorized_password_entry(
        self,
        request: BrowserRequest,
        *,
        kdbx_available: bool,
    ) -> tuple[Entry, Copy]:
        if request.alias is None:
            raise NativeHostError("invalid_alias", "credential alias is required")
        try:
            entry = self._garden.by_alias(request.alias)
        except GardenError as error:
            raise NativeHostError("credential_not_found", "credential alias was not found") from error
        if entry.kind != "password":
            raise NativeHostError("credential_kind_unsupported", "browser actions support password credentials only")
        if request.origin is None or not _entry_matches_origin(entry, request.origin):
            raise NativeHostError("origin_mismatch", "credential is not authorized for this page origin")
        home = entry.home_copy()
        if home.type == "secret_service":
            if self._tooling.secret_tool is None:
                raise NativeHostError("backend_unavailable", "GNOME Secret Service helper is unavailable")
            return entry, home
        if home.type == "kdbx":
            if not kdbx_available:
                raise NativeHostError(
                    "unlock_agent_unavailable",
                    "KDBX home is locked; start the Secretariat KDBX unlock agent",
                )
            return entry, home
        raise NativeHostError(
            "backend_unavailable",
            "this credential home is not available to the browser host",
        )

    def _kdbx_agent_available(self) -> bool:
        if not hasattr(socket, "AF_UNIX"):
            return False
        try:
            return self._kdbx_agent.available()
        except (KDBXAgentError, AttributeError):
            return False


def _credential_view(entry: Entry, tooling: Tooling, *, kdbx_available: bool) -> dict[str, Any]:
    home = entry.home_copy()
    if home.type == "secret_service":
        available = tooling.secret_tool is not None
        reason = None if available else "secret_service_helper_missing"
    elif home.type == "kdbx":
        available = kdbx_available
        reason = None if available else "kdbx_locked"
    else:
        available = False
        reason = "background_unlock_unavailable"
    return {
        "alias": entry.alias,
        "title": entry.title,
        "username": entry.username,
        "provider": entry.provider,
        "home_type": home.type,
        "fillable": available,
        "updatable": available,
        "unavailable_reason": reason,
    }


def _entry_matches_origin(entry: Entry, origin: str) -> bool:
    login = entry.links.get("login")
    if not login:
        return False
    try:
        return canonical_origin(login) == origin
    except BrowserProtocolError:
        return False


def serve(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    caller_origin: str,
    garden_path: Path,
) -> int:
    config = load_device_config(default_config_path())
    if caller_origin not in config.browser_allowed_extension_origins:
        return 3
    garden = load_garden(garden_path)
    broker = BrowserBroker(garden, Tooling.detect())

    while True:
        try:
            payload = read_message(input_stream)
        except NativeHostError as error:
            write_message(output_stream, error_response(None, error.code, str(error)))
            return 2
        if payload is None:
            return 0

        request_id = payload.get("request_id") if isinstance(payload, dict) else None
        try:
            request = parse_request(payload)
            response = broker.handle(request)
        except BrowserProtocolError as error:
            response = error_response(request_id if isinstance(request_id, str) else None, error.code, str(error))
        except NativeHostError as error:
            response = error_response(request_id if isinstance(request_id, str) else None, error.code, str(error))
        except (GardenError, BackendError, DeviceConfigError, KDBXAgentError):
            response = error_response(
                request_id if isinstance(request_id, str) else None,
                "host_failure",
                "Secretariat could not complete the browser request",
            )
        write_message(output_stream, response)


def read_message(stream: BinaryIO) -> Any | None:
    prefix = stream.read(4)
    if prefix == b"":
        return None
    if len(prefix) != 4:
        raise NativeHostError("invalid_frame", "native message length prefix is incomplete")
    size = int.from_bytes(prefix, byteorder=sys.byteorder, signed=False)
    if size <= 0 or size > MAX_MESSAGE_BYTES:
        raise NativeHostError("message_too_large", "native message exceeds the reviewed size bound")
    body = stream.read(size)
    if len(body) != size:
        raise NativeHostError("invalid_frame", "native message body is incomplete")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeHostError("invalid_json", "native message is not valid UTF-8 JSON") from error


def write_message(stream: BinaryIO, value: Any) -> None:
    try:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise NativeHostError("invalid_response", "native response could not be serialized") from error
    if len(body) > MAX_MESSAGE_BYTES:
        raise NativeHostError("response_too_large", "native response exceeds the reviewed size bound")
    stream.write(len(body).to_bytes(4, byteorder=sys.byteorder, signed=False))
    stream.write(body)
    stream.flush()


def _garden_path() -> Path:
    configured = os.environ.get("SECRETARIAT_GARDEN")
    return Path(configured).expanduser() if configured else Path("garden.json")


def _binary_stdio() -> tuple[BinaryIO, BinaryIO]:
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    return sys.stdin.buffer, sys.stdout.buffer


def main(arguments: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values:
        return 2
    caller_origin = values[0]
    input_stream, output_stream = _binary_stdio()
    try:
        return serve(
            input_stream,
            output_stream,
            caller_origin=caller_origin,
            garden_path=_garden_path(),
        )
    except (DeviceConfigError, GardenError, NativeHostError, KDBXAgentError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
