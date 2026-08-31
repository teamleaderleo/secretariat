from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from secretariat.reconcile import Group, ReconcileError, Report
from secretariat.report import reconciliation_html, write_reconciliation_html


class ReportTests(unittest.TestCase):
    def report(self):
        return Report(
            snapshot_count=3,
            observation_count=3,
            groups=(
                Group(
                    origin="https://example.com",
                    username='<script>alert("fixture")</script>',
                    classification="conflict",
                    copies=2,
                    sources=("apple_passwords", "chrome_passwords"),
                    source_counts=(("apple_passwords", 1), ("chrome_passwords", 1)),
                    note_sources=("apple_passwords",),
                    otp_sources=("apple_passwords",),
                ),
                Group(
                    origin="https://other.example",
                    username="user@example.com",
                    classification="single",
                    copies=1,
                    sources=("edge_passwords",),
                    source_counts=(("edge_passwords", 1),),
                    note_sources=(),
                    otp_sources=(),
                ),
            ),
            multi_account_origins=("https://example.com",),
        )

    def test_html_is_interactive_secret_free_and_escapes_text(self):
        rendered = reconciliation_html(self.report())
        self.assertIn("Secretariat reconciliation", rendered)
        self.assertIn('data-filter="conflict"', rendered)
        self.assertIn("OTP in apple_passwords", rendered)
        self.assertNotIn('<script>alert("fixture")</script>', rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_writer_creates_private_file_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.html"
            write_reconciliation_html(self.report(), path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(ReconcileError, "already exists"):
                write_reconciliation_html(self.report(), path)


if __name__ == "__main__":
    unittest.main()
