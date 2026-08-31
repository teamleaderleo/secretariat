from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from secretariat.reconcile import ReconcileError, SnapshotSpec, normalize_origin, reconcile


class ReconcileTests(unittest.TestCase):
    def write_csv(self, directory, name, headers, rows):
        path = Path(directory) / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)
        return path

    def test_duplicate_conflict_and_multiple_accounts_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            chrome = self.write_csv(
                directory,
                "chrome.csv",
                ["name", "url", "username", "password", "note"],
                [
                    ["Example", "https://example.com/login", "same@example.com", "generated-A", ""],
                    ["Example", "https://example.com/", "conflict@example.com", "generated-old", ""],
                    ["Example", "https://example.com/", "other@example.com", "generated-other", ""],
                ],
            )
            apple = self.write_csv(
                directory,
                "apple.csv",
                ["Title", "URL", "Username", "Password", "Notes", "OTPAuth"],
                [
                    ["Example", "https://EXAMPLE.com/account", "same@example.com", "generated-A", "generated-note", "generated-otp"],
                    ["Example", "https://example.com", "conflict@example.com", "generated-new", "", ""],
                ],
            )
            report = reconcile((SnapshotSpec("chrome_passwords", chrome), SnapshotSpec("apple_passwords", apple)))
            classes = {(group.username, group.classification) for group in report.groups}
            self.assertIn(("same@example.com", "duplicate"), classes)
            self.assertIn(("conflict@example.com", "conflict"), classes)
            self.assertIn(("other@example.com", "single"), classes)
            self.assertEqual(report.multi_account_origins, ("https://example.com",))
            same_group = next(group for group in report.groups if group.username == "same@example.com")
            self.assertEqual(same_group.note_sources, ("apple_passwords",))
            self.assertEqual(same_group.otp_sources, ("apple_passwords",))
            rendered = repr(report)
            for value in ("generated-A", "generated-old", "generated-new", "generated-note", "generated-otp"):
                self.assertNotIn(value, rendered)

    def test_same_source_duplicate_rows_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            chrome = self.write_csv(
                directory,
                "chrome.csv",
                ["url", "username", "password"],
                [["example.com/a", "user", "generated-A"], ["example.com/b", "user", "generated-A"]],
            )
            group = reconcile((SnapshotSpec("chrome_passwords", chrome),)).groups[0]
            self.assertEqual(group.classification, "duplicate")
            self.assertEqual(group.source_counts, (("chrome_passwords", 2),))

    def test_missing_required_columns_and_symlink_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            bad = self.write_csv(directory, "bad.csv", ["URL", "Username"], [["example.com", "user"]])
            with self.assertRaisesRegex(ReconcileError, "requires url, username, and password"):
                reconcile((SnapshotSpec("apple_passwords", bad),))

            real = self.write_csv(directory, "real.csv", ["url", "username", "password"], [["example.com", "user", "generated-A"]])
            link = Path(directory) / "link.csv"
            link.symlink_to(real)
            with self.assertRaisesRegex(ReconcileError, "symbolic link"):
                reconcile((SnapshotSpec("chrome_passwords", link),))

    def test_origin_normalization_is_conservative(self):
        self.assertEqual(normalize_origin("example.com/login"), "https://example.com")
        self.assertEqual(normalize_origin("https://EXAMPLE.com:443/path?q=1"), "https://example.com")
        self.assertEqual(normalize_origin("http://example.com:8080/a"), "http://example.com:8080")


if __name__ == "__main__":
    unittest.main()
