"""User-facing KDBX unlock-agent command with revision-aware status checks."""

from __future__ import annotations

import argparse
import getpass
import sys

from .backends import BackendError
from .config import DeviceConfigError, default_config_path, load_device_config
from .kdbx_agent import (
    KDBXAgentClient,
    KDBXAgentError,
    KDBXAgentServer,
    UnlockedKDBXSession,
    default_agent_socket_path,
)


class HealthCheckedServer(KDBXAgentServer):
    """Require the encrypted KDBX revision to still match before reporting unlocked."""

    def _dispatch(self, request):
        if request.action == "status":
            self.session._require_current_revision()
        return super()._dispatch(request)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="secretariat-kdbx-agent")
    commands = value.add_subparsers(dest="command", required=True)
    serve = commands.add_parser(
        "serve",
        help="Unlock the configured KDBX home and serve it in this foreground process",
    )
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
            server = HealthCheckedServer(
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
