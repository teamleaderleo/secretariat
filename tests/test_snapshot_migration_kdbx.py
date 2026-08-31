from __future__ import annotations

import csv
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from secretariat.garden import load_garden
from secretariat.reconcile import SnapshotSpec
from secretariat.snapshot_migration import migrate_snapshot_home_to_kdbx

try:
    from pykeepass import PyKeePass, create_database
except ImportError:
    PyKeePass = None
    create_database = None


@unittest.skipUnless(create_database is not None, "optional pykeepass dependency is not installed")
class SnapshotMigrationKDBXIntegrationTests(unittest.TestCase):
    def test_generated_snapshot_value_becomes_exact_uuid_portable_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            garden_path = root / "garden.json"
            garden_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "entries": [
                            {
                                "alias": "generated-login",
                                "title": "Generated login",
                                "username": "generated-user@example.invalid",
                                "kind": "password",
                                "provider": "example.invalid",
                                "copies": [
                                    {
                                        "id": "apple",
                                        "type": "apple_passwords",
                                        "reference": "https://example.invalid account=generated-user@example.invalid",
                                    }
                                ],
                                "home": "apple",
                                "links": {"login": "https://example.invalid/login"},
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            snapshot_path = root / "apple.csv"
            with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Title", "URL", "Username", "Password"])
                writer.writerow(
                    [
                        "Generated login",
                        "https://example.invalid/account",
                        "generated-user@example.invalid",
                        "SECRETARIAT-GENERATED-MIGRATION-VALUE",
                    ]
                )

            master = "SECRETARIAT-GENERATED-MIGRATION-MASTER"
            kdbx_path = root / "portable.kdbx"
            create_database(str(kdbx_path), password=master).save()
            result = migrate_snapshot_home_to_kdbx(
                garden_path,
                "generated-login",
                SnapshotSpec("apple_passwords", snapshot_path),
                kdbx_path=kdbx_path,
                password_provider=lambda: master,
            )

            entry = load_garden(garden_path).by_alias("generated-login")
            self.assertEqual(entry.home_copy().type, "kdbx")
            self.assertEqual(entry.home_copy().reference, result.kdbx_uuid)
            database = PyKeePass(str(kdbx_path), password=master)
            stored = database.find_entries(uuid=uuid.UUID(hex=result.kdbx_uuid), first=True)
            self.assertIsNotNone(stored)
            self.assertEqual(stored.password, "SECRETARIAT-GENERATED-MIGRATION-VALUE")


if __name__ == "__main__":
    unittest.main()
