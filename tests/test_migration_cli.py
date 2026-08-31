from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from secretariat.backends import Tooling
from secretariat.snapshot_migration import MigrationResult
from secretariat import migration_cli


class MigrationCLITests(unittest.TestCase):
    def tooling(self, *, pykeepass=True):
        return Tooling(None, None, None, pykeepass)

    def test_to_kdbx_dispatches_one_alias_and_snapshot_without_value_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = type("Config", (), {"kdbx_path": root / "portable.kdbx"})()
            output = io.StringIO()
            with (
                patch("secretariat.migration_cli.Tooling.detect", return_value=self.tooling()),
                patch("secretariat.migration_cli.load_device_config", return_value=config),
                patch("secretariat.migration_cli.default_config_path", return_value=root / "config.json"),
                patch(
                    "secretariat.migration_cli.migrate_snapshot_home_to_kdbx",
                    return_value=MigrationResult("example-login", "00112233445566778899aabbccddeeff"),
                ) as migrate,
                redirect_stdout(output),
            ):
                code = migration_cli.main(
                    [
                        "migrate",
                        "--garden",
                        str(root / "garden.json"),
                        "to-kdbx",
                        "example-login",
                        "--snapshot",
                        f"apple_passwords={root / 'apple.csv'}",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("migrated example-login", output.getvalue())
            self.assertIn("00112233445566778899aabbccddeeff", output.getvalue())
            called = migrate.call_args
            self.assertEqual(called.args[1], "example-login")
            self.assertEqual(called.args[2].source, "apple_passwords")

    def test_missing_kdbx_extra_fails_before_snapshot_access(self):
        errors = io.StringIO()
        with patch("secretariat.migration_cli.Tooling.detect", return_value=self.tooling(pykeepass=False)), redirect_stderr(errors):
            code = migration_cli.main(
                [
                    "migrate",
                    "to-kdbx",
                    "example-login",
                    "--snapshot",
                    "apple_passwords=/not/opened.csv",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("optional secretariat[kdbx] dependency", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
