"""Chrome/Edge native messaging host for explicit Secretariat browser actions."""

from __future__ import annotations

import json
import os
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
from .garden import Entry, Garden, GardenError, load_garden


class NativeHostError(RuntimeError):
    """Bounded native-host failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BrowserBroker:
    def __init__(self, garden: Garden, tooling: Tooling) -> None:
        self._garden = garden
        self._tooling = tooling

    def handle(self, request: BrowserRequest) -> dict[str, Any]:
        if request.action == "status":
            return ok_response(
                request.request_id,
                capabilities={
                    "match": True,
                    "get": self._tooling.secret_tool is not None,
                    "get_sources": ["secret_service"] if self._tooling.secret_tool is not None else [],
                },
            )

        if request.origin is None:
            raise NativeHostError("invalid_origin", "page origin is required")

        if request.action == "match":
            matches = tuple(entry for entry in self._garden.entries if _entry_matches_origin(entry, request.origin))
            return ok_response(
                request.request_id,
                credentials=[
                    _credential_view(entry, self._tooling)
                    for entry in matches
                    if entry.kind == "password"
                ],
            )

        if request.action == "get":
            if request.alias is None:
                raise NativeHostError("invalid_alias", "credential alias is required")
            try:
                entry = self._garden.by_alias(request.alias)
            except GardenError as error:
                raise NativeHostError("credential_not_found", "credential alias was not found") from error
            if entry.kind != "password":
                raise NativeHostError("credential_kind_unsupported", "browser fill supports password credentials only")
            if not _entry_matches_origin(entry, request.origin):
                raise NativeHostError("origin_mismatch", "credential is not authorized for this page origin")
            home = entry.home_copy()
            if home.type != "secret_service":
                raise NativeHostError(
                    "interactive_unlock_unavailable",
                    "this credential home cannot be opened by the browser host yet",
                )
            if self._tooling.secret_tool is None:
                raise NativeHostError("backend_unavailable", "GNOME Secret Service helper is unavailable")
            try:
                password = backend_for(home, self._tooling).load(home)
            except BackendError as error:
                raise NativeHostError("backend_unavailable", "credential could not be retrieved") from error
            return ok_response(request.request_id, username=entry.username, password=password)

        raise NativeHostError("unsupported_action", "request action is unsupported")


def _credential_view(entry: Entry, tooling: Tooling) -> dict[str, Any]:
    home = entry.home_copy()
    fillable = home.type == "secret_service" and tooling.secret_tool is not None
    reason = None
    if not fillable:
        reason = (
            "secret_service_helper_missing"
            if home.type == "secret_service"
            else "background_unlock_unavailable"
        )
    return {
        "alias": entry.alias,
        "title": entry.title,
        "username": entry.username,
        "provider": entry.provider,
        "home_type": home.type,
        "fillable": fillable,
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
        except (GardenError, BackendError, DeviceConfigError):
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
    except (DeviceConfigError, GardenError, NativeHostError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
