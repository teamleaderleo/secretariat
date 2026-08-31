"""Strict message protocol for the Secretariat browser bridge."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


PROTOCOL_VERSION = 1
HOST_NAME = "com.secretariat.browser"
MAX_MESSAGE_BYTES = 1_048_576
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
ACTIONS = frozenset({"status", "match", "get"})
COMMON_FIELDS = frozenset({"version", "request_id", "action"})
ACTION_FIELDS = {
    "status": COMMON_FIELDS,
    "match": COMMON_FIELDS | {"origin"},
    "get": COMMON_FIELDS | {"origin", "alias"},
}


class BrowserProtocolError(ValueError):
    """Bounded protocol failure safe to return to the extension."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BrowserRequest:
    request_id: str
    action: str
    origin: str | None = None
    alias: str | None = None


def parse_request(value: Any) -> BrowserRequest:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise BrowserProtocolError("invalid_request", "request must be a JSON object")

    version = value.get("version")
    if version != PROTOCOL_VERSION:
        raise BrowserProtocolError("unsupported_version", "protocol version is unsupported")

    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise BrowserProtocolError("invalid_request_id", "request id is invalid")

    action = value.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise BrowserProtocolError("unsupported_action", "request action is unsupported")

    allowed = ACTION_FIELDS[action]
    if set(value) != allowed:
        raise BrowserProtocolError("invalid_fields", "request fields do not match the action")

    origin = None
    alias = None
    if action in {"match", "get"}:
        raw_origin = value.get("origin")
        if not isinstance(raw_origin, str):
            raise BrowserProtocolError("invalid_origin", "page origin is invalid")
        origin = canonical_origin(raw_origin)

    if action == "get":
        raw_alias = value.get("alias")
        if not isinstance(raw_alias, str) or not ALIAS.fullmatch(raw_alias):
            raise BrowserProtocolError("invalid_alias", "credential alias is invalid")
        alias = raw_alias

    return BrowserRequest(request_id=request_id, action=action, origin=origin, alias=alias)


def canonical_origin(value: str) -> str:
    if len(value) > 2_048:
        raise BrowserProtocolError("invalid_origin", "page origin is invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise BrowserProtocolError("invalid_origin", "page origin is invalid") from error
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        raise BrowserProtocolError("invalid_origin", "page origin is invalid")
    host = hostname.rstrip(".").casefold()
    if not host:
        raise BrowserProtocolError("invalid_origin", "page origin is invalid")
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    authority = host if port is None or default_port else f"{host}:{port}"
    return f"{scheme}://{authority}"


def ok_response(request_id: str, **payload: Any) -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": True,
        **payload,
    }


def error_response(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    response: dict[str, Any] = {
        "version": PROTOCOL_VERSION,
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if request_id is not None and REQUEST_ID.fullmatch(request_id):
        response["request_id"] = request_id
    return response
