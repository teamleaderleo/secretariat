from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from secretariat.garden import GardenError, parse_garden


EXAMPLE = Path(__file__).resolve().parents[1] / "garden.example.json"


class GardenTests(unittest.TestCase):
    def document(self):
        return json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_example_is_strict_secret_free_metadata(self):
        garden = parse_garden(self.document())
        entry = garden.by_alias("example-api-token")
        self.assertEqual(entry.delivery.name, "EXAMPLE_API_TOKEN")
        self.assertEqual(entry.due_on(), date(2026, 9, 29))
        self.assertEqual(entry.home_copy().type, "secret_service")
        browser = garden.by_alias("example-browser-login")
        self.assertEqual(browser.username, "generated-user@example.invalid")
        self.assertEqual(len(browser.copies), 2)
        self.assertEqual(browser.home_copy().type, "apple_passwords")
        self.assertIsNone(browser.delivery)

    def test_optional_fields_keep_simple_single_copy_entries_small(self):
        document = {
            "schema_version": 3,
            "entries": [
                {
                    "alias": "github-web",
                    "title": "GitHub",
                    "kind": "password",
                    "provider": "github",
                    "copies": [
                        {
                            "id": "apple",
                            "type": "apple_passwords",
                            "reference": "github.com/login",
                        }
                    ],
                }
            ],
        }
        entry = parse_garden(document).by_alias("github-web")
        self.assertEqual(entry.status, "active")
        self.assertIsNone(entry.username)
        self.assertEqual(entry.scopes, ())
        self.assertEqual(entry.home_copy().id, "apple")

    def test_multi_copy_entry_requires_valid_home(self):
        document = self.document()
        document["entries"][1].pop("home")
        with self.assertRaisesRegex(GardenError, "requires a home"):
            parse_garden(document)

        document = self.document()
        document["entries"][1]["home"] = "missing"
        with self.assertRaisesRegex(GardenError, "does not name"):
            parse_garden(document)

    def test_duplicate_copy_ids_fail(self):
        document = self.document()
        document["entries"][1]["copies"][1]["id"] = "apple"
        with self.assertRaisesRegex(GardenError, "duplicate copy id"):
            parse_garden(document)

    def test_kdbx_copy_requires_canonical_uuid(self):
        document = {
            "schema_version": 3,
            "entries": [
                {
                    "alias": "portable-example",
                    "title": "Portable example",
                    "kind": "password",
                    "provider": "example",
                    "copies": [
                        {
                            "id": "portable",
                            "type": "kdbx",
                            "reference": "00112233445566778899aabbccddeeff",
                        }
                    ],
                }
            ],
        }
        entry = parse_garden(document).by_alias("portable-example")
        self.assertEqual(entry.home_copy().reference, "00112233445566778899aabbccddeeff")

        invalid = (
            "General/portable-example",
            "{00112233-4455-6677-8899-aabbccddeeff}",
            "00112233445566778899AABBCCDDEEFF",
        )
        for reference in invalid:
            with self.subTest(reference=reference):
                document["entries"][0]["copies"][0]["reference"] = reference
                with self.assertRaisesRegex(GardenError, "canonical lowercase"):
                    parse_garden(document)

    def test_unknown_and_value_bearing_fields_fail_closed(self):
        document = self.document()
        document["entries"][0]["convenient_extra"] = "nope"
        with self.assertRaisesRegex(GardenError, "unknown field"):
            parse_garden(document)

    def test_username_is_optional_single_line_account_metadata(self):
        document = self.document()
        document["entries"][1]["username"] = "generated-second-user@example.invalid"
        entry = parse_garden(document).by_alias("example-browser-login")
        self.assertEqual(entry.username, "generated-second-user@example.invalid")

        for invalid in ("", "line one\nline two", "account\x7f"):
            with self.subTest(invalid=invalid):
                document["entries"][1]["username"] = invalid
                with self.assertRaisesRegex(GardenError, "username is invalid"):
                    parse_garden(document)

        document = self.document()
        document["entries"][0]["token_value"] = "generated-test-sentinel"
        with self.assertRaisesRegex(GardenError, "forbidden value-bearing"):
            parse_garden(document)

    def test_find_matches_across_copy_metadata(self):
        garden = parse_garden(self.document())
        self.assertEqual(
            tuple(entry.alias for entry in garden.find("browser chrome")),
            ("example-browser-login",),
        )


if __name__ == "__main__":
    unittest.main()
