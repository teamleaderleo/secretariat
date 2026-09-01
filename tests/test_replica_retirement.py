from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from secretariat.garden import load_garden
from secretariat.reconcile import SnapshotSpec
from secretariat.replica_retirement import (
    ReplicaRetirementError,
    load_replica_receipt,
    retire_replica_from_receipt,
    verify_replica_convergence,
    write_replica_receipt,
)


class ReplicaRetirementTests(unittest.TestCase):
    kdbx_uuid = "00112233445566778899aabbccddeeff"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.garden_path = self.root / "garden.json"
        self.write_garden()

    def write_garden(self, *, home="portable", apple_reference="https://example.com account=generated-user@example.invalid"):
        self.garden_path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "entries": [
                        {
                            "alias": "example-login",
                            "title": "Example login",
                            "username": "generated-user@example.invalid",
                            "kind": "password",
                            "provider": "example.com",
                            "copies": [
                                {
                                    "id": "portable",
                                    "type": "kdbx",
                                    "reference": self.kdbx_uuid,
                                },
                                {
                                    "id": "apple",
                                    "type": "apple_passwords",
                                    "reference": apple_reference,
                                },
                            ],
                            "home": home,
                            "links": {"login": "https://example.com/login"},
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_snapshot(self, *, value="generated-current", notes="", otp=""):
        path = self.root / "apple.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Title", "URL", "Username", "Password", "Notes", "OTPAuth"])
            writer.writerow(
                [
                    "Example",
                    "https://example.com/account",
                    "generated-user@example.invalid",
                    value,
                    notes,
                    otp,
                ]
            )
        return SnapshotSpec("apple_passwords", path)

    def verify(self, *, snapshot=None, home_value="generated-current"):
        return verify_replica_convergence(
            self.garden_path,
            "example-login",
            "apple",
            snapshot or self.write_snapshot(),
            load_home=lambda _copy: home_value,
            now=lambda: datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc),
        )

    def test_matching_values_create_secret_free_private_receipt(self):
        receipt = self.verify(snapshot=self.write_snapshot(notes="generated-note", otp="otpauth://generated-fixture"))
        self.assertTrue(receipt.notes_present)
        self.assertTrue(receipt.otp_present)
        self.assertEqual(receipt.matching_rows, 1)
        self.assertEqual(receipt.verified_at, "2026-08-31T23:59:00Z")
        self.assertNotIn("generated-current", repr(receipt))

        path = self.root / "receipt.json"
        write_replica_receipt(receipt, path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        rendered = path.read_text(encoding="utf-8")
        for secret in ("generated-current", "generated-note", "otpauth://generated-fixture"):
            self.assertNotIn(secret, rendered)
        parsed = load_replica_receipt(path)
        self.assertEqual(parsed.replica.id, "apple")
        self.assertTrue(parsed.attached_data_present)

    def test_mismatch_wrong_source_and_home_target_are_refused(self):
        with self.assertRaisesRegex(ReplicaRetirementError, "does not match"):
            self.verify(home_value="generated-different")

        wrong = self.root / "chrome.csv"
        wrong.write_text("url,username,password\nhttps://example.com,generated-user@example.invalid,generated-current\n", encoding="utf-8")
        with self.assertRaisesRegex(ReplicaRetirementError, "snapshot source does not match"):
            verify_replica_convergence(
                self.garden_path,
                "example-login",
                "apple",
                SnapshotSpec("chrome_passwords", wrong),
                load_home=lambda _copy: "generated-current",
            )

        with self.assertRaisesRegex(ReplicaRetirementError, "current home copy"):
            verify_replica_convergence(
                self.garden_path,
                "example-login",
                "portable",
                self.write_snapshot(),
                load_home=lambda _copy: "generated-current",
            )

    def test_attached_data_requires_ack_then_only_garden_metadata_is_removed(self):
        receipt = self.verify(snapshot=self.write_snapshot(notes="generated-note"))
        receipt_path = self.root / "receipt.json"
        write_replica_receipt(receipt, receipt_path)
        before = self.garden_path.read_bytes()

        with self.assertRaisesRegex(ReplicaRetirementError, "--ack-attached-data"):
            retire_replica_from_receipt(self.garden_path, receipt_path)
        self.assertEqual(self.garden_path.read_bytes(), before)

        retired = retire_replica_from_receipt(
            self.garden_path,
            receipt_path,
            acknowledge_attached_data=True,
        )
        self.assertEqual(retired.replica.type, "apple_passwords")
        entry = load_garden(self.garden_path).by_alias("example-login")
        self.assertEqual(tuple(copy.id for copy in entry.copies), ("portable",))
        self.assertEqual(entry.home_copy().id, "portable")

    def test_changed_replica_or_home_invalidates_receipt_without_mutation(self):
        receipt = self.verify()
        receipt_path = self.root / "receipt.json"
        write_replica_receipt(receipt, receipt_path)

        self.write_garden(apple_reference="changed-reference")
        before = self.garden_path.read_bytes()
        with self.assertRaisesRegex(ReplicaRetirementError, "replica changed"):
            retire_replica_from_receipt(self.garden_path, receipt_path)
        self.assertEqual(self.garden_path.read_bytes(), before)

        self.write_garden(home="apple")
        before = self.garden_path.read_bytes()
        with self.assertRaisesRegex(ReplicaRetirementError, "home changed|became the Garden home"):
            retire_replica_from_receipt(self.garden_path, receipt_path)
        self.assertEqual(self.garden_path.read_bytes(), before)

    def test_symlink_and_unknown_receipts_are_refused(self):
        receipt = self.verify()
        real = self.root / "receipt.json"
        write_replica_receipt(receipt, real)
        link = self.root / "receipt-link.json"
        link.symlink_to(real)
        with self.assertRaisesRegex(ReplicaRetirementError, "symbolic link"):
            load_replica_receipt(link)

        document = receipt.document()
        document["convenient_extra"] = "nope"
        forged = self.root / "forged.json"
        forged.write_text(json.dumps(document) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ReplicaRetirementError, "schema is unsupported"):
            load_replica_receipt(forged)


if __name__ == "__main__":
    unittest.main()
