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

    def test_unknown_and_value_bearing_fields_fail_closed(self):
        document = self.document()
        document["entries"][0]["convenient_extra"] = "nope"
        with self.assertRaisesRegex(GardenError, "unknown field"):
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
