from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from secretariat import cli


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "garden.example.json"


class FakeBackend:
    SENTINEL = "generated-sentinel-value-for-tests"

    def load(self, _copy):
        return self.SENTINEL


class CliTests(unittest.TestCase):
    def tooling(self, secret_tool=None, wl_copy=None, macos_security=None):
        return cli.Tooling(secret_tool, wl_copy, macos_security)

    def test_external_garden_environment_variable(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"SECRETARIAT_GARDEN": str(EXAMPLE)}), redirect_stdout(output):
            code = cli.main(["find", "chrome"])
        self.assertEqual(code, 0)
        self.assertIn("example-browser-login", output.getvalue())

    def test_explicit_garden_path_overrides_environment(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"SECRETARIAT_GARDEN": "/does/not/exist"}), redirect_stdout(output):
            code = cli.main(["--garden", str(EXAMPLE), "find", "chrome"])
        self.assertEqual(code, 0)

    def test_indexed_only_home_refuses_value_access(self):
        errors = io.StringIO()
        with patch("secretariat.cli.Tooling.detect", return_value=self.tooling()), redirect_stderr(errors):
            code = cli.main(["--garden", str(EXAMPLE), "copy", "example-browser-login"])
        self.assertEqual(code, 2)
        self.assertIn("indexed only", errors.getvalue())

    def test_run_uses_home_copy(self):
        observed = {}

        def fake_run(child, *, env, check):
            observed["child"] = child
            observed["value"] = env["EXAMPLE_API_TOKEN"]
            return type("Result", (), {"returncode": 7})()

        with (
            patch("secretariat.cli.Tooling.detect", return_value=self.tooling(secret_tool="fixture")),
            patch("secretariat.cli.backend_for", return_value=FakeBackend()),
            patch("secretariat.cli.subprocess.run", side_effect=fake_run),
        ):
            code = cli.main(["--garden", str(EXAMPLE), "run", "example-api-token", "--", "fixture-child"])
        self.assertEqual(code, 7)
        self.assertEqual(observed["child"], ["fixture-child"])
        self.assertEqual(observed["value"], FakeBackend.SENTINEL)

    def test_reconcile_json_and_html_never_output_password_values(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "chrome.csv"
            second = Path(directory) / "edge.csv"
            html = Path(directory) / "review.html"
            for path, password in ((first, "generated-one"), (second, "generated-two")):
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["url", "username", "password"])
                    writer.writerow(["https://example.com/login", "user@example.com", password])
            output = io.StringIO()
            with redirect_stdout(output):
                code = cli.main([
                    "--json",
                    "reconcile",
                    "--snapshot", f"chrome_passwords={first}",
                    "--snapshot", f"edge_passwords={second}",
                    "--html", str(html),
                ])
            self.assertEqual(code, 0)
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["groups"][0]["classification"], "conflict")
            rendered = output.getvalue() + html.read_text(encoding="utf-8")
            self.assertNotIn("generated-one", rendered)
            self.assertNotIn("generated-two", rendered)


if __name__ == "__main__":
    unittest.main()
