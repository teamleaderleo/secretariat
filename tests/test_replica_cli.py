from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from secretariat import app, replica_cli
from secretariat.config import DeviceConfig
from secretariat.garden import Copy
from secretariat.replica_retirement import ReplicaReceipt


class ReplicaCLITests(unittest.TestCase):
    def receipt(self, *, attached=False):
        return ReplicaReceipt(
            alias="example-login",
            verified_at=datetime(2026, 8, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            username="generated-user@example.invalid",
            login="https://example.invalid/login",
            home=Copy("portable", "kdbx", "00112233445566778899aabbccddeeff"),
            replica=Copy("apple", "apple_passwords", "https://example.invalid account=generated-user@example.invalid"),
            notes_present=attached,
            otp_present=False,
            matching_rows=1,
        )

    def test_verify_writes_receipt_and_reports_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            receipt = self.receipt()
            output = io.StringIO()
            with (
                patch("secretariat.replica_cli.Tooling.detect"),
                patch("secretariat.replica_cli.load_device_config", return_value=DeviceConfig()),
                patch("secretariat.replica_cli.default_config_path", return_value=root / "config.json"),
                patch("secretariat.replica_cli.KDBXAgentClient.available", return_value=False),
                patch("secretariat.replica_cli.verify_replica_convergence", return_value=receipt) as verify,
                patch("secretariat.replica_cli.write_replica_receipt") as write,
                redirect_stdout(output),
            ):
                code = replica_cli.main(
                    [
                        "--garden",
                        str(root / "garden.json"),
                        "replica",
                        "verify",
                        "example-login",
                        "--copy-id",
                        "apple",
                        "--snapshot",
                        f"apple_passwords={root / 'apple.csv'}",
                        "--receipt",
                        str(receipt_path),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("verified replica apple", output.getvalue())
            self.assertNotIn("password", output.getvalue().casefold())
            verify.assert_called_once()
            write.assert_called_once_with(receipt, receipt_path)

    def test_retire_reports_external_source_was_not_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = self.receipt(attached=True)
            output = io.StringIO()
            with (
                patch("secretariat.replica_cli.retire_replica_from_receipt", return_value=receipt) as retire,
                redirect_stdout(output),
            ):
                code = replica_cli.main(
                    [
                        "--garden",
                        str(root / "garden.json"),
                        "replica",
                        "retire",
                        "--receipt",
                        str(root / "receipt.json"),
                        "--ack-attached-data",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("was not deleted", output.getvalue())
            retire.assert_called_once_with(
                root / "garden.json",
                root / "receipt.json",
                acknowledge_attached_data=True,
            )

    def test_top_level_dispatch_routes_replica_with_global_garden(self):
        arguments = [
            "--garden",
            "/private/generated-garden.json",
            "replica",
            "retire",
            "--receipt",
            "/private/generated-receipt.json",
        ]
        with patch("secretariat.app.replica_cli.main", return_value=6) as replica:
            self.assertEqual(app.main(arguments), 6)
        replica.assert_called_once_with(arguments)


if __name__ == "__main__":
    unittest.main()
