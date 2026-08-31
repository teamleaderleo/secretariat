from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from secretariat.garden import Copy
from secretariat.kdbx_agent import (
    AgentRequest,
    KDBXAgentClient,
    KDBXAgentError,
    KDBXAgentServer,
    parse_agent_request,
)


class FakeSession:
    def __init__(self):
        self.values = {"0" * 32: "generated-agent-old"}
        self.closed = False

    def load(self, entry_uuid):
        return self.values[entry_uuid]

    def store(self, entry_uuid, value):
        self.values[entry_uuid] = value

    def close(self):
        self.closed = True


class KDBXAgentTests(unittest.TestCase):
    reference = "0" * 32

    def test_protocol_is_action_specific_and_hides_put_value_from_repr(self):
        request = parse_agent_request(
            {
                "version": 1,
                "request_id": "request-1",
                "action": "put",
                "uuid": self.reference,
                "value": "generated-agent-value",
            }
        )
        self.assertEqual(request, AgentRequest("request-1", "put", self.reference, "generated-agent-value"))
        self.assertNotIn("generated-agent-value", repr(request))

        with self.assertRaisesRegex(KDBXAgentError, "fields do not match"):
            parse_agent_request(
                {
                    "version": 1,
                    "request_id": "request-1",
                    "action": "status",
                    "value": "generated-agent-value",
                }
            )
        with self.assertRaisesRegex(KDBXAgentError, "UUID is invalid"):
            parse_agent_request(
                {
                    "version": 1,
                    "request_id": "request-1",
                    "action": "get",
                    "uuid": "not-a-uuid",
                }
            )

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix-domain sockets are unavailable")
    def test_round_trip_permissions_update_and_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "run" / "agent.sock"
            session = FakeSession()
            server = KDBXAgentServer(socket_path, session, idle_seconds=30, ttl_seconds=60)
            server.open()
            thread = threading.Thread(target=server.serve, daemon=True)
            thread.start()
            self.addCleanup(lambda: server.close())

            self.assertEqual(socket_path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(socket_path.stat().st_mode & 0o777, 0o600)

            client = KDBXAgentClient(socket_path)
            self.assertTrue(client.available())
            source = Copy("portable", "kdbx", self.reference)
            self.assertEqual(client.load(source), "generated-agent-old")
            client.store(source, "generated-agent-new")
            self.assertEqual(session.values[self.reference], "generated-agent-new")
            client.lock()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertTrue(session.closed)
            self.assertFalse(socket_path.exists())

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix-domain sockets are unavailable")
    def test_idle_timeout_closes_session_without_status_extending_it(self):
        class Clock:
            value = 0.0

            def __call__(self):
                return self.value

        with tempfile.TemporaryDirectory() as directory:
            clock = Clock()
            socket_path = Path(directory) / "run" / "agent.sock"
            session = FakeSession()
            server = KDBXAgentServer(
                socket_path,
                session,
                idle_seconds=30,
                ttl_seconds=60,
                clock=clock,
            )
            server.open()
            client = KDBXAgentClient(socket_path)

            thread = threading.Thread(target=server.serve, daemon=True)
            thread.start()
            self.assertTrue(client.available())
            clock.value = 31.0
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertTrue(session.closed)

    @unittest.skipUnless(hasattr(socket, "AF_UNIX"), "Unix-domain sockets are unavailable")
    def test_non_socket_path_is_never_unlinked(self):
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "run" / "agent.sock"
            socket_path.parent.mkdir()
            socket_path.write_text("do not remove", encoding="utf-8")
            server = KDBXAgentServer(socket_path, FakeSession(), idle_seconds=30, ttl_seconds=60)
            with self.assertRaisesRegex(KDBXAgentError, "non-socket"):
                server.open()
            self.assertEqual(socket_path.read_text(encoding="utf-8"), "do not remove")

    def test_client_rejects_non_kdbx_copy_before_connection(self):
        client = KDBXAgentClient(Path("/definitely/not/used"))
        with self.assertRaisesRegex(KDBXAgentError, "exact canonical KDBX"):
            client.load(Copy("copy", "chrome_passwords", "fixture"))


if __name__ == "__main__":
    unittest.main()
