from __future__ import annotations

import unittest

from secretariat.kdbx_agent import AgentRequest, KDBXAgentServer
from secretariat.kdbx_agent_cli import HealthCheckedServer


class FakeSession:
    active = True

    def __init__(self):
        self.checks = 0

    def _require_current_revision(self):
        self.checks += 1

    def close(self):
        self.active = False


class KDBXAgentCLIStatusTests(unittest.TestCase):
    def test_status_checks_encrypted_revision_before_reporting_unlocked(self):
        session = FakeSession()
        server = HealthCheckedServer(
            __import__("pathlib").Path("/tmp/not-opened-secretariat-agent.sock"),
            session,
            idle_seconds=30,
            ttl_seconds=60,
            clock=lambda: 0.0,
        )
        response = server._dispatch(AgentRequest("r", "status"))
        self.assertEqual(session.checks, 1)
        self.assertTrue(response["unlocked"])

    def test_non_status_dispatch_preserves_core_behavior(self):
        session = FakeSession()
        server = HealthCheckedServer(
            __import__("pathlib").Path("/tmp/not-opened-secretariat-agent.sock"),
            session,
            idle_seconds=30,
            ttl_seconds=60,
            clock=lambda: 0.0,
        )
        response = server._dispatch(AgentRequest("r", "lock"))
        self.assertEqual(session.checks, 0)
        self.assertTrue(response["locked"])
        self.assertIsInstance(server, KDBXAgentServer)


if __name__ == "__main__":
    unittest.main()
