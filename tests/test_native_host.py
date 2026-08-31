from __future__ import annotations

import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from secretariat.backends import Tooling
from secretariat.browser_protocol import BrowserRequest
from secretariat.config import DeviceConfig
from secretariat.garden import Copy, Entry, Garden
from secretariat.native_host import BrowserBroker, NativeHostError, read_message, serve, write_message


CALLER = "chrome-extension://abcdefghijklmnopabcdefghijklmnop/"


class FakeBackend:
    def __init__(self):
        self.stored = []

    def load(self, _copy):
        return "generated-browser-password"

    def store(self, source, value, label):
        self.stored.append((source.reference, value, label))


class FakeAgent:
    def __init__(self, available=False):
        self.is_available = available
        self.stored = []

    def available(self):
        return self.is_available

    def load(self, source):
        return "generated-kdbx-browser-password"

    def store(self, source, value):
        self.stored.append((source.reference, value))


class NativeHostTests(unittest.TestCase):
    def garden(self, home_type="secret_service"):
        entry = Entry(
            alias="example-login",
            title="Example login",
            username="generated-user@example.invalid",
            kind="password",
            provider="example",
            purpose="",
            environment="personal",
            status="active",
            scopes=(),
            copies=(Copy("home", home_type, "fixture" if home_type != "kdbx" else "0" * 32),),
            home="home",
            delivery=None,
            created_at=None,
            expires_at=None,
            rotate_by=None,
            last_tested_at=None,
            public_fingerprint=None,
            links={"login": "https://example.com/login"},
            notes="",
        )
        other = Entry(
            alias="other-login",
            title="Other login",
            username="other-generated-user@example.invalid",
            kind="password",
            provider="other",
            purpose="",
            environment="personal",
            status="active",
            scopes=(),
            copies=(Copy("home", "secret_service", "other"),),
            home="home",
            delivery=None,
            created_at=None,
            expires_at=None,
            rotate_by=None,
            last_tested_at=None,
            public_fingerprint=None,
            links={"login": "https://other.example/login"},
            notes="",
        )
        return Garden((entry, other))

    def broker(self, garden=None, tooling=None, *, agent_available=False):
        return BrowserBroker(
            garden or self.garden(),
            tooling or Tooling("secret-tool", None, None),
            kdbx_agent=FakeAgent(agent_available),
        )

    def test_match_is_bound_to_exact_login_origin(self):
        garden = self.garden()
        second = replace(
            garden.entries[0],
            alias="example-login-second",
            title="Example login second account",
            username="generated-second-user@example.invalid",
            copies=(Copy("home", "secret_service", "second-fixture"),),
        )
        broker = self.broker(Garden((*garden.entries, second)))
        response = broker.handle(BrowserRequest("r1", "match", origin="https://example.com"))
        self.assertTrue(response["ok"])
        self.assertEqual(
            [(item["alias"], item["username"]) for item in response["credentials"]],
            [
                ("example-login", "generated-user@example.invalid"),
                ("example-login-second", "generated-second-user@example.invalid"),
            ],
        )
        self.assertTrue(all(item["fillable"] for item in response["credentials"]))
        self.assertTrue(all(item["updatable"] for item in response["credentials"]))

    def test_get_checks_origin_and_only_returns_value_after_authorization(self):
        broker = self.broker()
        with patch("secretariat.native_host.backend_for", return_value=FakeBackend()):
            response = broker.handle(
                BrowserRequest("r1", "get", origin="https://example.com", alias="example-login")
            )
        self.assertEqual(response["password"], "generated-browser-password")
        self.assertEqual(response["username"], "generated-user@example.invalid")

        with self.assertRaisesRegex(NativeHostError, "not authorized"):
            broker.handle(BrowserRequest("r2", "get", origin="https://evil.example", alias="example-login"))

    def test_update_checks_origin_and_returns_no_value(self):
        sentinel = "SECRETARIAT-GENERATED-ONLY-UPDATE-0002"
        backend = FakeBackend()
        broker = self.broker()
        with patch("secretariat.native_host.backend_for", return_value=backend):
            response = broker.handle(
                BrowserRequest(
                    "r1",
                    "update",
                    origin="https://example.com",
                    alias="example-login",
                    password=sentinel,
                )
            )
        self.assertEqual(response["updated"], True)
        self.assertNotIn(sentinel, json.dumps(response))
        self.assertEqual(backend.stored, [("fixture", sentinel, "Example login")])

        backend.stored.clear()
        with self.assertRaisesRegex(NativeHostError, "not authorized"):
            broker.handle(
                BrowserRequest(
                    "r2",
                    "update",
                    origin="https://evil.example",
                    alias="example-login",
                    password=sentinel,
                )
            )
        self.assertEqual(backend.stored, [])

    def test_kdbx_home_is_visible_as_locked_without_agent(self):
        broker = self.broker(
            self.garden(home_type="kdbx"),
            Tooling(None, None, None, True),
            agent_available=False,
        )
        response = broker.handle(BrowserRequest("m", "match", origin="https://example.com"))
        self.assertFalse(response["credentials"][0]["fillable"])
        self.assertEqual(response["credentials"][0]["unavailable_reason"], "kdbx_locked")
        with self.assertRaisesRegex(NativeHostError, "KDBX home is locked"):
            broker.handle(BrowserRequest("r", "get", origin="https://example.com", alias="example-login"))

    def test_running_agent_makes_kdbx_home_fillable_and_updatable(self):
        agent = FakeAgent(True)
        broker = BrowserBroker(
            self.garden(home_type="kdbx"),
            Tooling(None, None, None, False),
            kdbx_agent=agent,
        )
        status = broker.handle(BrowserRequest("s", "status"))
        self.assertIn("kdbx", status["capabilities"]["get_sources"])
        match = broker.handle(BrowserRequest("m", "match", origin="https://example.com"))
        self.assertTrue(match["credentials"][0]["fillable"])
        self.assertTrue(match["credentials"][0]["updatable"])

        response = broker.handle(BrowserRequest("g", "get", origin="https://example.com", alias="example-login"))
        self.assertEqual(response["password"], "generated-kdbx-browser-password")
        sentinel = "SECRETARIAT-GENERATED-ONLY-KDBX-UPDATE"
        update = broker.handle(
            BrowserRequest(
                "u",
                "update",
                origin="https://example.com",
                alias="example-login",
                password=sentinel,
            )
        )
        self.assertTrue(update["updated"])
        self.assertNotIn(sentinel, json.dumps(update))
        self.assertEqual(agent.stored, [("0" * 32, sentinel)])

    def test_frame_round_trip_and_bounds(self):
        stream = io.BytesIO()
        write_message(stream, {"version": 1, "request_id": "r", "action": "status"})
        stream.seek(0)
        self.assertEqual(read_message(stream)["action"], "status")

        oversized = (1_048_577).to_bytes(4, byteorder=__import__("sys").byteorder)
        with self.assertRaisesRegex(NativeHostError, "size bound"):
            read_message(io.BytesIO(oversized))

    def test_serve_requires_authorized_extension_origin(self):
        request_stream = io.BytesIO()
        write_message(request_stream, {"version": 1, "request_id": "r", "action": "status"})
        request_stream.seek(0)
        output = io.BytesIO()
        config = DeviceConfig(browser_allowed_extension_origins=(CALLER,))
        with patch("secretariat.native_host.load_device_config", return_value=config):
            code = serve(
                request_stream,
                output,
                caller_origin="chrome-extension://pppppppppppppppppppppppppppppppp/",
                garden_path=Path("unused.json"),
            )
        self.assertEqual(code, 3)
        self.assertEqual(output.getvalue(), b"")

    def test_serve_returns_bounded_status_response(self):
        request_stream = io.BytesIO()
        write_message(request_stream, {"version": 1, "request_id": "r", "action": "status"})
        request_stream.seek(0)
        output = io.BytesIO()
        config = DeviceConfig(browser_allowed_extension_origins=(CALLER,))
        with (
            patch("secretariat.native_host.load_device_config", return_value=config),
            patch("secretariat.native_host.load_garden", return_value=self.garden()),
            patch("secretariat.native_host.Tooling.detect", return_value=Tooling(None, None, None)),
            patch("secretariat.native_host.KDBXAgentClient.available", return_value=False),
        ):
            code = serve(request_stream, output, caller_origin=CALLER, garden_path=Path("unused.json"))
        self.assertEqual(code, 0)
        output.seek(0)
        response = read_message(output)
        self.assertTrue(response["ok"])
        self.assertEqual(response["request_id"], "r")
        self.assertFalse(response["capabilities"]["update"])
        self.assertNotIn("generated-browser-password", json.dumps(response))


if __name__ == "__main__":
    unittest.main()
