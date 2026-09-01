from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from secretariat.backends import Tooling
from secretariat.config import DeviceConfig
from secretariat.home_state import inspect_portable_home
from secretariat.kdbx_agent import KDBXAgentError


class FakeAgent:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def request(self, action):
        self.calls.append(action)
        if self.error is not None:
            raise self.error
        return self.response or {}


class PortableHomeStateTests(unittest.TestCase):
    def tooling(self, *, pykeepass=True):
        return Tooling(None, None, None, pykeepass)

    def test_dependency_config_and_file_states_do_not_probe_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.kdbx"
            agent = FakeAgent(response={"unlocked": True})

            missing_dependency = inspect_portable_home(
                self.tooling(pykeepass=False),
                DeviceConfig(kdbx_path=path),
                agent=agent,
            )
            self.assertEqual(missing_dependency.state, "dependency_missing")
            self.assertEqual(agent.calls, [])

            missing_config = inspect_portable_home(
                self.tooling(),
                DeviceConfig(),
                agent=agent,
            )
            self.assertEqual(missing_config.state, "config_missing")
            self.assertEqual(agent.calls, [])

            missing_file = inspect_portable_home(
                self.tooling(),
                DeviceConfig(kdbx_path=path),
                agent=agent,
            )
            self.assertEqual(missing_file.state, "file_missing")
            self.assertEqual(agent.calls, [])

    def test_symlink_kdbx_path_is_unsafe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.kdbx"
            real.write_bytes(b"generated-encrypted-fixture")
            link = root / "link.kdbx"
            link.symlink_to(real)
            status = inspect_portable_home(
                self.tooling(),
                DeviceConfig(kdbx_path=link),
                agent=FakeAgent(),
            )
            self.assertEqual(status.state, "path_unsafe")
            self.assertEqual(status.kdbx_file, "unsafe")

    def test_unlocked_status_includes_remaining_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "home.kdbx"
            path.write_bytes(b"generated-encrypted-fixture")
            status = inspect_portable_home(
                self.tooling(),
                DeviceConfig(kdbx_path=path),
                agent=FakeAgent(
                    response={
                        "unlocked": True,
                        "idle_seconds_remaining": 500,
                        "ttl_seconds_remaining": 3000,
                    }
                ),
            )
            self.assertEqual(status.state, "available_unlocked")
            self.assertEqual(status.agent, "unlocked")
            self.assertEqual(status.idle_seconds_remaining, 500)
            self.assertEqual(status.ttl_seconds_remaining, 3000)

    def test_locked_invalidated_and_unsafe_agent_states_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "home.kdbx"
            path.write_bytes(b"generated-encrypted-fixture")
            cases = (
                ("agent_unavailable", "available_locked", "locked"),
                ("backend_failure", "changed_since_unlock", "invalidated"),
                ("socket_path", "agent_unsafe", "unsafe_endpoint"),
                ("unexpected", "agent_unavailable", "unavailable"),
            )
            for code, expected_state, expected_agent in cases:
                with self.subTest(code=code):
                    status = inspect_portable_home(
                        self.tooling(),
                        DeviceConfig(kdbx_path=path),
                        agent=FakeAgent(error=KDBXAgentError(code, "bounded fixture")),
                    )
                    self.assertEqual(status.state, expected_state)
                    self.assertEqual(status.agent, expected_agent)


if __name__ == "__main__":
    unittest.main()
