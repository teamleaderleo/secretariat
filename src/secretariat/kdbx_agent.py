"""Explicit foreground KDBX unlock agent over a user-only Unix-domain socket."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import stat
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .backends import BackendError, KDBXBackend, _encrypted_fingerprint, _save_database
from .config import DeviceConfigError, default_config_path, load_device_config
from .garden import Copy


AGENT_PROTOCOL_VERSION = 1
MAX_AGENT_MESSAGE_BYTES = 1_048_576
MAX_AGENT_VALUE_CHARS = 65_536
MAX_SOCKET_PATH_BYTES = 96
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ENTRY_UUID = re.compile(r"^[0-9a-f]{32}$")
ACTIONS = frozenset({"status", "get", "put", "lock"})
COMMON_FIELDS = frozenset({"version", "request_id", "action"})
ACTION_FIELDS = {
    "status": COMMON_FIELDS,
    "get": COMMON_FIELDS | {"uuid"},
    "put": COMMON_FIELDS | {"uuid", "value"},
    "lock": COMMON_FIELDS,
}


class KDBXAgentError(RuntimeError):
    """Bounded unlock-agent failure that never includes credential values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgentRequest:
    request_id: str
    action: str
    entry_uuid: str | None = None
    value: str | None = field(default=None, repr=False)


class UnlockedKDBXSession:
    """One explicitly unlocked KDBX object bound to one encrypted-file revision."""

    def __init__(self, path: Path, database: Any, baseline: tuple[int, int, bytes]) -> None:
        self._path = path.expanduser()
        self._database = database
        self._baseline = baseline
        self._closed = False

    @classmethod
    def open(cls, path: Path, password: str) -> "UnlockedKDBXSession":
        target = path.expanduser()
        if not isinstance(password, str) or not password:
            raise BackendError("KDBX unlock was cancelled or empty")
        if target.is_symlink():
            raise BackendError("KDBX path must not be a symbolic link")
        if not target.is_file():
            raise BackendError("KDBX database is unavailable at the configured path")
        try:
            from pykeepass import PyKeePass
        except ImportError as error:
            raise BackendError("KDBX support requires the optional secretariat[kdbx] dependency") from error

        baseline = _encrypted_fingerprint(target)
        try:
            database = PyKeePass(str(target), password=password)
        except Exception as error:
            raise BackendError("KDBX database could not be opened with the supplied unlock credential") from error
        if _encrypted_fingerprint(target) != baseline:
            raise BackendError("KDBX home changed while the unlock agent was opening it")
        return cls(target, database, baseline)

    def load(self, entry_uuid: str) -> str:
        self._require_current_revision()
        entry = self._entry(entry_uuid)
        value = entry.password
        if not isinstance(value, str) or not value:
            raise BackendError("credential is absent from the KDBX entry")
        self._require_current_revision()
        return value

    def store(self, entry_uuid: str, value: str) -> None:
        if not isinstance(value, str) or not value or len(value) > MAX_AGENT_VALUE_CHARS:
            raise BackendError("credential value is empty or exceeds the agent bound")
        self._require_current_revision()
        entry = self._entry(entry_uuid)
        current = entry.password or ""
        if current == value:
            self._require_current_revision()
            return
        entry.save_history()
        entry.password = value
        entry.touch(modify=True)
        try:
            _save_database(self._database, self._path, self._baseline)
            self._baseline = _encrypted_fingerprint(self._path)
        except BackendError as error:
            self.close()
            raise BackendError("KDBX unlock-agent session was invalidated after a failed write") from error

    def close(self) -> None:
        self._database = None
        self._baseline = None
        self._closed = True

    def _entry(self, entry_uuid: str):
        source = Copy("agent", "kdbx", entry_uuid)
        return KDBXBackend._entry(self._database, source)

    def _require_current_revision(self) -> None:
        if self._closed or self._database is None or self._baseline is None:
            raise BackendError("KDBX unlock-agent session is locked")
        if _encrypted_fingerprint(self._path) != self._baseline:
            self.close()
            raise BackendError("KDBX home changed since unlock; unlock-agent session was invalidated")


class KDBXAgentServer:
    def __init__(
        self,
        socket_path: Path,
        session: UnlockedKDBXSession,
        *,
        idle_seconds: int = 900,
        ttl_seconds: int = 7_200,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_seconds < 30 or idle_seconds > 86_400:
            raise KDBXAgentError("invalid_timeout", "agent idle timeout must be between 30 and 86400 seconds")
        if ttl_seconds < idle_seconds or ttl_seconds > 86_400:
            raise KDBXAgentError("invalid_timeout", "agent TTL must be between the idle timeout and 86400 seconds")
        self.socket_path = socket_path.expanduser()
        self.session = session
        self.idle_seconds = idle_seconds
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.started_at = clock()
        self.last_value_activity = self.started_at
        self._listener: socket.socket | None = None
        self._stopping = False

    def open(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise KDBXAgentError("unsupported_platform", "KDBX unlock agent requires Unix-domain sockets")
        _ensure_secure_runtime_directory(self.socket_path.parent)
        _validate_socket_path_length(self.socket_path)
        _clear_stale_socket(self.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            old_umask = os.umask(0o077)
            try:
                listener.bind(str(self.socket_path))
            finally:
                os.umask(old_umask)
            os.chmod(self.socket_path, 0o600)
            listener.listen(8)
            listener.settimeout(0.5)
        except Exception:
            listener.close()
            try:
                self.socket_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        self._listener = listener

    def serve(self) -> int:
        if self._listener is None:
            self.open()
        assert self._listener is not None
        try:
            while not self._stopping:
                now = self.clock()
                if now - self.started_at >= self.ttl_seconds:
                    break
                if now - self.last_value_activity >= self.idle_seconds:
                    break
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                except OSError as error:
                    if self._stopping:
                        break
                    raise KDBXAgentError("socket_failure", "unlock-agent socket accept failed") from error
                with connection:
                    connection.settimeout(5)
                    self._handle_connection(connection)
            return 0
        finally:
            self.close()

    def close(self) -> None:
        self._stopping = True
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
            self._listener = None
        self.session.close()
        try:
            self.socket_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _handle_connection(self, connection: socket.socket) -> None:
        request_id: str | None = None
        try:
            payload = _recv_message(connection)
            request_id_value = payload.get("request_id") if isinstance(payload, dict) else None
            request_id = request_id_value if isinstance(request_id_value, str) else None
            request = parse_agent_request(payload)
            response = self._dispatch(request)
        except KDBXAgentError as error:
            response = agent_error_response(request_id, error.code, str(error))
        except BackendError:
            response = agent_error_response(request_id, "backend_failure", "KDBX unlock agent could not complete the request")
        _send_message(connection, response)

    def _dispatch(self, request: AgentRequest) -> dict[str, Any]:
        if request.action == "status":
            now = self.clock()
            return agent_ok_response(
                request.request_id,
                unlocked=True,
                idle_seconds_remaining=max(0, int(self.idle_seconds - (now - self.last_value_activity))),
                ttl_seconds_remaining=max(0, int(self.ttl_seconds - (now - self.started_at))),
            )
        if request.action == "lock":
            self._stopping = True
            return agent_ok_response(request.request_id, locked=True)
        if request.action == "get":
            assert request.entry_uuid is not None
            value = self.session.load(request.entry_uuid)
            self.last_value_activity = self.clock()
            return agent_ok_response(request.request_id, value=value)
        if request.action == "put":
            assert request.entry_uuid is not None and request.value is not None
            self.session.store(request.entry_uuid, request.value)
            self.last_value_activity = self.clock()
            return agent_ok_response(request.request_id, updated=True)
        raise KDBXAgentError("unsupported_action", "unlock-agent action is unsupported")


class KDBXAgentClient:
    def __init__(self, socket_path: Path | None = None, *, timeout: float = 2.0) -> None:
        self.socket_path = (socket_path or default_agent_socket_path()).expanduser()
        self.timeout = timeout

    def available(self) -> bool:
        try:
            response = self.request("status")
        except KDBXAgentError:
            return False
        return response.get("unlocked") is True

    def load(self, source: Copy) -> str:
        _require_kdbx_copy(source)
        response = self.request("get", entry_uuid=source.reference)
        value = response.get("value")
        if not isinstance(value, str) or not value:
            raise KDBXAgentError("invalid_response", "unlock agent returned no credential value")
        return value

    def store(self, source: Copy, value: str) -> None:
        _require_kdbx_copy(source)
        if not isinstance(value, str) or not value or len(value) > MAX_AGENT_VALUE_CHARS:
            raise KDBXAgentError("invalid_value", "credential value is empty or exceeds the agent bound")
        response = self.request("put", entry_uuid=source.reference, value=value)
        if response.get("updated") is not True:
            raise KDBXAgentError("invalid_response", "unlock agent did not confirm the update")

    def lock(self) -> None:
        response = self.request("lock")
        if response.get("locked") is not True:
            raise KDBXAgentError("invalid_response", "unlock agent did not confirm lock")

    def request(self, action: str, *, entry_uuid: str | None = None, value: str | None = None) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        request: dict[str, Any] = {
            "version": AGENT_PROTOCOL_VERSION,
            "request_id": request_id,
            "action": action,
        }
        if entry_uuid is not None:
            request["uuid"] = entry_uuid
        if value is not None:
            request["value"] = value
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout)
                connection.connect(str(self.socket_path))
                _send_message(connection, request)
                response = _recv_message(connection)
        except (OSError, TimeoutError) as error:
            raise KDBXAgentError("agent_unavailable", "KDBX unlock agent is unavailable") from error
        if not isinstance(response, dict) or response.get("version") != AGENT_PROTOCOL_VERSION:
            raise KDBXAgentError("invalid_response", "KDBX unlock agent returned an invalid response")
        if response.get("request_id") != request_id:
            raise KDBXAgentError("invalid_response", "KDBX unlock agent response id did not match")
        if response.get("ok") is not True:
            error = response.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise KDBXAgentError(
                code if isinstance(code, str) else "agent_failure",
                message if isinstance(message, str) else "KDBX unlock agent rejected the request",
            )
        return response


def parse_agent_request(value: Any) -> AgentRequest:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise KDBXAgentError("invalid_request", "unlock-agent request must be a JSON object")
    if value.get("version") != AGENT_PROTOCOL_VERSION:
        raise KDBXAgentError("unsupported_version", "unlock-agent protocol version is unsupported")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise KDBXAgentError("invalid_request_id", "unlock-agent request id is invalid")
    action = value.get("action")
    if not isinstance(action, str) or action not in ACTIONS:
        raise KDBXAgentError("unsupported_action", "unlock-agent action is unsupported")
    if set(value) != ACTION_FIELDS[action]:
        raise KDBXAgentError("invalid_fields", "unlock-agent request fields do not match the action")

    entry_uuid = None
    if action in {"get", "put"}:
        raw_uuid = value.get("uuid")
        if not isinstance(raw_uuid, str) or not ENTRY_UUID.fullmatch(raw_uuid):
            raise KDBXAgentError("invalid_uuid", "unlock-agent KDBX UUID is invalid")
        entry_uuid = raw_uuid

    secret = None
    if action == "put":
        raw_value = value.get("value")
        if not isinstance(raw_value, str) or not raw_value or len(raw_value) > MAX_AGENT_VALUE_CHARS:
            raise KDBXAgentError("invalid_value", "credential value is empty or exceeds the agent bound")
        secret = raw_value
    return AgentRequest(request_id, action, entry_uuid, secret)


def agent_ok_response(request_id: str, **payload: Any) -> dict[str, Any]:
    return {"version": AGENT_PROTOCOL_VERSION, "request_id": request_id, "ok": True, **payload}


def agent_error_response(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    response: dict[str, Any] = {
        "version": AGENT_PROTOCOL_VERSION,
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if isinstance(request_id, str) and REQUEST_ID.fullmatch(request_id):
        response["request_id"] = request_id
    return response


def default_agent_socket_path() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "Secretariat" / "run"
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        base = Path(runtime).expanduser() / "secretariat" if runtime else Path.home() / ".cache" / "secretariat" / "run"
    return base / "kdbx-agent.sock"


def _ensure_secure_runtime_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        metadata = path.lstat()
    except OSError as error:
        raise KDBXAgentError("runtime_directory", "unlock-agent runtime directory is unavailable") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise KDBXAgentError("runtime_directory", "unlock-agent runtime path must be a real directory")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise KDBXAgentError("runtime_directory", "unlock-agent runtime directory is not owned by this user")
    try:
        os.chmod(path, 0o700)
    except OSError as error:
        raise KDBXAgentError("runtime_directory", "unlock-agent runtime directory permissions could not be secured") from error


def _clear_stale_socket(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise KDBXAgentError("socket_path", "unlock-agent socket path could not be inspected") from error
    if not stat.S_ISSOCK(metadata.st_mode):
        raise KDBXAgentError("socket_path", "unlock-agent socket path is occupied by a non-socket file")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise KDBXAgentError("socket_path", "unlock-agent socket is not owned by this user")
    client = KDBXAgentClient(path, timeout=0.25)
    if client.available():
        raise KDBXAgentError("already_running", "KDBX unlock agent is already running")
    try:
        path.unlink()
    except OSError as error:
        raise KDBXAgentError("socket_path", "stale unlock-agent socket could not be removed") from error


def _validate_socket_path_length(path: Path) -> None:
    if len(os.fsencode(str(path))) > MAX_SOCKET_PATH_BYTES:
        raise KDBXAgentError("socket_path", "unlock-agent socket path is too long for the supported Unix platforms")


def _require_kdbx_copy(source: Copy) -> None:
    if source.type != "kdbx" or not ENTRY_UUID.fullmatch(source.reference):
        raise KDBXAgentError("invalid_uuid", "unlock agent requires an exact canonical KDBX copy UUID")


def _recv_message(connection: socket.socket) -> Any:
    prefix = _recv_exact(connection, 4)
    if len(prefix) != 4:
        raise KDBXAgentError("invalid_frame", "unlock-agent message length prefix is incomplete")
    size = int.from_bytes(prefix, "big", signed=False)
    if size <= 0 or size > MAX_AGENT_MESSAGE_BYTES:
        raise KDBXAgentError("message_too_large", "unlock-agent message exceeds the reviewed size bound")
    body = _recv_exact(connection, size)
    if len(body) != size:
        raise KDBXAgentError("invalid_frame", "unlock-agent message body is incomplete")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise KDBXAgentError("invalid_json", "unlock-agent message is not valid UTF-8 JSON") from error


def _send_message(connection: socket.socket, value: Any) -> None:
    try:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise KDBXAgentError("invalid_message", "unlock-agent message could not be serialized") from error
    if not body or len(body) > MAX_AGENT_MESSAGE_BYTES:
        raise KDBXAgentError("message_too_large", "unlock-agent message exceeds the reviewed size bound")
    try:
        connection.sendall(len(body).to_bytes(4, "big", signed=False) + body)
    except OSError as error:
        raise KDBXAgentError("socket_failure", "unlock-agent message could not be sent") from error


def _recv_exact(connection: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = connection.recv(size - len(chunks))
        except OSError as error:
            raise KDBXAgentError("socket_failure", "unlock-agent message could not be received") from error
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat-kdbx-agent")
    commands = value.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Unlock the configured KDBX home and serve it in this foreground process")
    serve.add_argument("--idle-seconds", type=int, default=900)
    serve.add_argument("--ttl-seconds", type=int, default=7_200)
    commands.add_parser("status", help="Show secret-free unlock-agent status")
    commands.add_parser("lock", help="Explicitly lock the running KDBX unlock agent")
    return value


def main(arguments: list[str] | None = None) -> int:
    args = parser().parse_args(arguments)
    client = KDBXAgentClient()
    try:
        if args.command == "status":
            response = client.request("status")
            print(
                "unlocked: yes\n"
                f"idle_seconds_remaining: {response['idle_seconds_remaining']}\n"
                f"ttl_seconds_remaining: {response['ttl_seconds_remaining']}"
            )
            return 0
        if args.command == "lock":
            client.lock()
            print("KDBX unlock agent locked")
            return 0
        if args.command == "serve":
            config = load_device_config(default_config_path())
            if config.kdbx_path is None:
                raise KDBXAgentError("config_missing", "KDBX home path is not configured on this device")
            password = getpass.getpass("KDBX master password: ")
            try:
                session = UnlockedKDBXSession.open(config.kdbx_path, password)
            finally:
                password = ""
            server = KDBXAgentServer(
                default_agent_socket_path(),
                session,
                idle_seconds=args.idle_seconds,
                ttl_seconds=args.ttl_seconds,
            )
            server.open()
            print("KDBX unlock agent is ready; keep this process running to allow enrolled KDBX access")
            return server.serve()
        raise KDBXAgentError("unsupported_action", "unlock-agent command is unsupported")
    except (KDBXAgentError, BackendError, DeviceConfigError) as error:
        print(f"secretariat-kdbx-agent: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
