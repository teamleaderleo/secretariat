from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from secretariat.backends import KDBXBackend
from secretariat.garden import load_garden
from secretariat.reconcile import SnapshotSpec
from secretariat.replica_retirement import verify_replica_convergence

try:
    from pykeepass import create_database
except ImportError:
    create_database = None


@unittest.skipUnless(create_database is not None, "optional pykeepass dependency is not installed")
class ReplicaRetirementKDBXIntegrationTests(unittest.TestCase):
    def test_generated_snapshot_replica_matches_real_kdbx_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            master = "SECRETARIAT-GENERATED-REPLICA-MASTER"
            kdbx_path = root / "home.kdbx"
            database = create_database(str(kdbx_path), password=master)
            entry = database.add_entry(
                database.root_group,
                "Generated login",
                "generated-user@example.invalid",
                "SECRETARIAT-GENERATED-REPLICA-VALUE",
                url="https://example.invalid/login",
            )
            database.save()
            reference = entry.uuid.hex.lower()

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
                                    {"id": "portable", "type": "kdbx", "reference": reference},
                                    {
                                        "id": "apple",
                                        "type": "apple_passwords",
                                        "reference": "https://example.invalid account=generated-user@example.invalid",
                                    },
                                ],
                                "home": "portable",
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
                        "SECRETARIAT-GENERATED-REPLICA-VALUE",
                    ]
                )

            garden_entry = load_garden(garden_path).by_alias("generated-login")
            backend = KDBXBackend(kdbx_path, lambda: master)
            receipt = verify_replica_convergence(
                garden_path,
                "generated-login",
                "apple",
                SnapshotSpec("apple_passwords", snapshot_path),
                load_home=lambda _copy: backend.load(garden_entry.home_copy()),
            )
            self.assertEqual(receipt.home.reference, reference)
            self.assertEqual(receipt.replica.type, "apple_passwords")
            self.assertFalse(receipt.attached_data_present)


if __name__ == "__main__":
    unittest.main()
