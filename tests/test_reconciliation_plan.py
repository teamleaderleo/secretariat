from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from secretariat.garden import load_garden
from secretariat.reconcile import Group
from secretariat.reconciliation_plan import (
    ReconciliationPlanError,
    apply_reconciliation_plan,
    default_alias,
    parse_reconciliation_plan,
    plan_template,
)


class ReconciliationPlanTests(unittest.TestCase):
    def entry(self, *, alias="example-user", home="chrome"):
        return {
            "alias": alias,
            "title": "Example",
            "username": "generated-user@example.invalid",
            "provider": "example.com",
            "login": "https://example.com",
            "copies": [
                {
                    "id": "chrome",
                    "type": "chrome_passwords",
                    "reference": "https://example.com account=generated-user@example.invalid",
                },
                {
                    "id": "apple",
                    "type": "apple_passwords",
                    "reference": "https://example.com account=generated-user@example.invalid",
                },
            ],
            "home": home,
        }

    def document(self, *entries):
        return {"schema_version": 1, "entries": list(entries or (self.entry(),))}

    def test_plan_template_is_secret_free_and_stable(self):
        group = Group(
            origin="https://example.com",
            title="Example",
            username="generated-user@example.invalid",
            classification="conflict",
            copies=2,
            sources=("apple_passwords", "chrome_passwords"),
            source_counts=(("apple_passwords", 1), ("chrome_passwords", 1)),
            note_sources=(),
            otp_sources=(),
        )
        template = plan_template(group)
        self.assertEqual(template["provider"], "example.com")
        self.assertIsNone(template["home"])
        self.assertEqual([copy["id"] for copy in template["copies"]], ["apple", "chrome"])
        self.assertEqual(template["alias"], default_alias(group.origin, group.username))
        rendered = repr(template)
        self.assertNotIn("password", rendered.casefold())

    def test_plan_requires_exact_fields_sources_and_home(self):
        plan = parse_reconciliation_plan(self.document())
        self.assertEqual(plan.entries[0].home, "chrome")

        invalid = self.document()
        invalid["entries"][0]["convenient_extra"] = "nope"
        with self.assertRaisesRegex(ReconciliationPlanError, "fields are invalid"):
            parse_reconciliation_plan(invalid)

        invalid = self.document()
        invalid["entries"][0]["home"] = "missing"
        with self.assertRaisesRegex(ReconciliationPlanError, "does not name"):
            parse_reconciliation_plan(invalid)

        invalid = self.document()
        invalid["entries"][0]["copies"][0]["type"] = "secret_service"
        with self.assertRaisesRegex(ReconciliationPlanError, "source is unsupported"):
            parse_reconciliation_plan(invalid)

    def test_apply_is_atomic_and_refuses_alias_collisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            garden_path = root / "garden.json"
            garden_path.write_text(json.dumps({"schema_version": 3, "entries": []}) + "\n", encoding="utf-8")
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self.document()) + "\n", encoding="utf-8")

            aliases = apply_reconciliation_plan(garden_path, plan_path)
            self.assertEqual(aliases, ("example-user",))
            entry = load_garden(garden_path).by_alias("example-user")
            self.assertEqual(entry.home_copy().id, "chrome")
            self.assertEqual(entry.username, "generated-user@example.invalid")
            self.assertEqual(entry.links["login"], "https://example.com")

            before = garden_path.read_bytes()
            with self.assertRaisesRegex(ReconciliationPlanError, "already contains"):
                apply_reconciliation_plan(garden_path, plan_path)
            self.assertEqual(garden_path.read_bytes(), before)

    def test_bad_second_entry_leaves_garden_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            garden_path = root / "garden.json"
            garden_path.write_text(json.dumps({"schema_version": 3, "entries": []}) + "\n", encoding="utf-8")
            before = garden_path.read_bytes()
            second = self.entry(alias="bad-entry")
            second["home"] = "missing"
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(self.document(self.entry(), second)) + "\n", encoding="utf-8")

            with self.assertRaises(ReconciliationPlanError):
                apply_reconciliation_plan(garden_path, plan_path)
            self.assertEqual(garden_path.read_bytes(), before)

    def test_symlink_plan_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            garden_path = root / "garden.json"
            garden_path.write_text(json.dumps({"schema_version": 3, "entries": []}) + "\n", encoding="utf-8")
            real = root / "plan.json"
            real.write_text(json.dumps(self.document()) + "\n", encoding="utf-8")
            link = root / "plan-link.json"
            link.symlink_to(real)
            with self.assertRaisesRegex(ReconciliationPlanError, "symbolic link"):
                apply_reconciliation_plan(garden_path, link)


if __name__ == "__main__":
    unittest.main()
