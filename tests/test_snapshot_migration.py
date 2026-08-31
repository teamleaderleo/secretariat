from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretariat.garden import load_garden
from secretariat.garden_edit import GardenEditError
from secretariat.reconcile import SnapshotSpec
from secretariat.snapshot_migration import (
    SnapshotMigrationError,
    SnapshotMigrationOrphanError,
    migrate_snapshot_home_to_kdbx,
    select_snapshot_value,
)


class SnapshotMigrationTests(unittest.TestCase):
    kdbx_uuid = "00112233445566778899aabbccddeeff"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.garden_path = self.root / "garden.json"
        self.write_garden()

    def write_garden(self, *, home="apple", login="https://example.com/login", username="generated-user@example.invalid"):
        entry = {
            "alias": "example-login",
            "title": "Example login",
            "username": username,
            "kind": "password",
            "provider": "example.com",
            "copies": [
                {
                    "id": "apple",
                    "type": "apple_passwords",
                    "reference": "https://example.com account=generated-user@example.invalid",
                },
                {
                    "id": "chrome",
                    "type": "chrome_passwords",
                    "reference": "https://example.com account=generated-user@example.invalid",
                },
            ],
            "home": home,
        }
        if login is not None:
            entry["links"] = {"login": login}
        self.garden_path.write_text(
            json.dumps({"schema_version": 3, "entries": [entry]}) + "\n",
            encoding="utf-8",
        )

    def write_snapshot(self, source, rows):
        path = self.root / f"{source}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Title", "URL", "Username", "Password"])
            writer.writerows(rows)
        return SnapshotSpec(source, path)

    def test_selects_exact_home_source_origin_and_username(self):
        snapshot = self.write_snapshot(
            "apple_passwords",
            [
                ["Wrong account", "https://example.com", "other@example.invalid", "generated-other"],
                ["Wrong site", "https://other.example", "generated-user@example.invalid", "generated-other"],
                ["Right", "https://example.com/account", "generated-user@example.invalid", "generated-right"],
            ],
        )
        selection = select_snapshot_value(self.garden_path, "example-login", snapshot)
        self.assertEqual(selection.source, "apple_passwords")
        self.assertEqual(selection.value, "generated-right")
        self.assertNotIn("generated-right", repr(selection))

    def test_duplicate_equal_rows_are_accepted_but_conflicting_rows_fail(self):
        equal = self.write_snapshot(
            "apple_passwords",
            [
                ["Right", "https://example.com/a", "generated-user@example.invalid", "generated-same"],
                ["Right", "https://example.com/b", "generated-user@example.invalid", "generated-same"],
            ],
        )
        self.assertEqual(
            select_snapshot_value(self.garden_path, "example-login", equal).value,
            "generated-same",
        )

        conflicting = self.write_snapshot(
            "apple_passwords",
            [
                ["Right", "https://example.com/a", "generated-user@example.invalid", "generated-old"],
                ["Right", "https://example.com/b", "generated-user@example.invalid", "generated-new"],
            ],
        )
        with self.assertRaisesRegex(SnapshotMigrationError, "conflicting passwords"):
            select_snapshot_value(self.garden_path, "example-login", conflicting)

    def test_wrong_source_and_missing_login_are_refused(self):
        chrome = self.write_snapshot(
            "chrome_passwords",
            [["Right", "https://example.com", "generated-user@example.invalid", "generated-value"]],
        )
        with self.assertRaisesRegex(SnapshotMigrationError, "does not match"):
            select_snapshot_value(self.garden_path, "example-login", chrome)

        self.write_garden(login=None)
        apple = self.write_snapshot(
            "apple_passwords",
            [["Right", "https://example.com", "generated-user@example.invalid", "generated-value"]],
        )
        with self.assertRaisesRegex(SnapshotMigrationError, "explicit Garden login"):
            select_snapshot_value(self.garden_path, "example-login", apple)

    def test_success_writes_kdbx_then_promotes_portable_copy(self):
        snapshot = self.write_snapshot(
            "apple_passwords",
            [["Right", "https://example.com", "generated-user@example.invalid", "generated-value"]],
        )
        captured = {}

        def fake_add(path, password_provider, *, title, username, url, value):
            captured.update(path=path, title=title, username=username, url=url, value=value)
            return self.kdbx_uuid

        result = migrate_snapshot_home_to_kdbx(
            self.garden_path,
            "example-login",
            snapshot,
            kdbx_path=self.root / "home.kdbx",
            password_provider=lambda: "generated-master",
            add_entry=fake_add,
        )
        self.assertEqual(result.kdbx_uuid, self.kdbx_uuid)
        self.assertEqual(captured["value"], "generated-value")
        entry = load_garden(self.garden_path).by_alias("example-login")
        self.assertEqual(entry.home_copy().type, "kdbx")
        self.assertEqual(entry.home_copy().reference, self.kdbx_uuid)
        self.assertEqual({copy.type for copy in entry.copies}, {"apple_passwords", "chrome_passwords", "kdbx"})

    def test_garden_race_preserves_uuid_and_recovery_argv(self):
        snapshot = self.write_snapshot(
            "apple_passwords",
            [["Right", "https://example.com", "generated-user@example.invalid", "generated-value"]],
        )
        before = self.garden_path.read_bytes()
        with patch(
            "secretariat.snapshot_migration.commit_prepared",
            side_effect=GardenEditError("Garden diverged before save; review the competing revision"),
        ):
            with self.assertRaises(SnapshotMigrationOrphanError) as captured:
                migrate_snapshot_home_to_kdbx(
                    self.garden_path,
                    "example-login",
                    snapshot,
                    kdbx_path=self.root / "home.kdbx",
                    password_provider=lambda: "generated-master",
                    add_entry=lambda *args, **kwargs: self.kdbx_uuid,
                )
        error = captured.exception
        self.assertEqual(error.kdbx_uuid, self.kdbx_uuid)
        self.assertIn("garden", error.recovery_argv)
        self.assertIn("attach", error.recovery_argv)
        self.assertIn("--home", error.recovery_argv)
        self.assertIn(self.kdbx_uuid, error.recovery_argv)
        self.assertEqual(self.garden_path.read_bytes(), before)

    def test_existing_portable_copy_is_refused_before_kdbx_write(self):
        document = json.loads(self.garden_path.read_text(encoding="utf-8"))
        document["entries"][0]["copies"].append(
            {"id": "portable", "type": "kdbx", "reference": self.kdbx_uuid}
        )
        self.garden_path.write_text(json.dumps(document) + "\n", encoding="utf-8")
        snapshot = self.write_snapshot(
            "apple_passwords",
            [["Right", "https://example.com", "generated-user@example.invalid", "generated-value"]],
        )
        called = []
        with self.assertRaisesRegex(SnapshotMigrationError, "already contains"):
            migrate_snapshot_home_to_kdbx(
                self.garden_path,
                "example-login",
                snapshot,
                kdbx_path=self.root / "home.kdbx",
                password_provider=lambda: "generated-master",
                add_entry=lambda *args, **kwargs: called.append(True) or self.kdbx_uuid,
            )
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
