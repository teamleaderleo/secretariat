from __future__ import annotations

import unittest

from secretariat.browser_protocol import BrowserProtocolError, canonical_origin, parse_request


class BrowserProtocolTests(unittest.TestCase):
    def test_origin_normalization_is_exact(self):
        self.assertEqual(canonical_origin("https://EXAMPLE.com:443/login?q=1"), "https://example.com")
        self.assertEqual(canonical_origin("http://example.com:8080/path"), "http://example.com:8080")
        with self.assertRaisesRegex(BrowserProtocolError, "origin is invalid"):
            canonical_origin("https://user:credential@example.com/")
        with self.assertRaisesRegex(BrowserProtocolError, "origin is invalid"):
            canonical_origin("file:///tmp/example")

    def test_request_fields_are_action_specific(self):
        request = parse_request(
            {
                "version": 1,
                "request_id": "request-1",
                "action": "get",
                "origin": "https://example.com/login",
                "alias": "example-login",
            }
        )
        self.assertEqual(request.origin, "https://example.com")
        self.assertEqual(request.alias, "example-login")

        with self.assertRaisesRegex(BrowserProtocolError, "fields do not match"):
            parse_request(
                {
                    "version": 1,
                    "request_id": "request-1",
                    "action": "status",
                    "origin": "https://example.com",
                }
            )

    def test_unknown_version_action_and_alias_fail_closed(self):
        with self.assertRaisesRegex(BrowserProtocolError, "version is unsupported"):
            parse_request({"version": 2, "request_id": "r", "action": "status"})
        with self.assertRaisesRegex(BrowserProtocolError, "action is unsupported"):
            parse_request({"version": 1, "request_id": "r", "action": "delete"})
        with self.assertRaisesRegex(BrowserProtocolError, "alias is invalid"):
            parse_request(
                {
                    "version": 1,
                    "request_id": "r",
                    "action": "get",
                    "origin": "https://example.com",
                    "alias": "../../secret",
                }
            )


if __name__ == "__main__":
    unittest.main()
