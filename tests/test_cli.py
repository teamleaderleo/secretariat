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
from secretariat.garden import load_garden


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "garden.example.json"


class FakeBackend:
    SENTINEL = "generated-sentinel-value-for-tests"

    def load(self, _copy):
        return self.SENTINEL


class CliTests(unittest.TestCase):
    def tooling(self, secret_tool=None, wl_copy=None, macos_security=None, pykeepass=False):
        return cli.Tooling(secret_tool, wl_copy, macos_security, pykeepass)

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

    def test_home_status_does_not_require_a_garden(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portable.kdbx"
            config = type("Config", (), {"kdbx_path": path})()
            output = io.StringIO()
            with (
                patch("secretariat.cli.Tooling.detect", return_value=self.tooling(pykeepass=True)),
                patch("secretariat.cli.load_device_config", return_value=config),
                patch("secretariat.cli.default_config_path", return_value=Path(directory) / "config.json"),
                redirect_stdout(output),
            ):
                code = cli.main(["home", "status"])
        self.assertEqual(code, 0)
        self.assertIn("kdbx_path: configured", output.getvalue())
        self.assertIn("kdbx_file: missing", output.getvalue())

    def test_home_init_prompts_without_printing_master_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portable.kdbx"
            config = type("Config", (), {"kdbx_path": path})()
            output = io.StringIO()
            errors = io.StringIO()
            master = "generated-master-password"
            with (
                patch("secretariat.cli.Tooling.detect", return_value=self.tooling(pykeepass=True)),
                patch("secretariat.cli.load_device_config", return_value=config),
                patch("secretariat.cli.default_config_path", return_value=Path(directory) / "config.json"),
                patch("secretariat.cli.getpass.getpass", side_effect=[master, master]),
                patch("secretariat.cli.create_kdbx_home") as create,
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                code = cli.main(["home", "init"])
            self.assertEqual(code, 0)
            create.assert_called_once_with(path, master)
            self.assertNotIn(master, output.getvalue() + errors.getvalue())

    def test_home_add_prints_uuid_only_and_keeps_values_out_of_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portable.kdbx"
            config = type("Config", (), {"kdbx_path": path})()
            output = io.StringIO()
            errors = io.StringIO()
            value = "generated-credential-value"
            master = "generated-master-password"
            reference = "00112233445566778899aabbccddeeff"
            observed = {}

            def fake_add(kdbx_path, password_provider, *, title, username, url, value):
                observed["path"] = kdbx_path
                observed["master"] = password_provider()
                observed["title"] = title
                observed["username"] = username
                observed["url"] = url
                observed["value"] = value
                return reference

            with (
                patch("secretariat.cli.Tooling.detect", return_value=self.tooling(pykeepass=True)),
                patch("secretariat.cli.load_device_config", return_value=config),
                patch("secretariat.cli.default_config_path", return_value=Path(directory) / "config.json"),
                patch("secretariat.cli.getpass.getpass", side_effect=[value, value, master]),
                patch("secretariat.cli.add_kdbx_entry", side_effect=fake_add),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                code = cli.main([
                    "home", "add",
                    "--title", "Example",
                    "--username", "user@example.invalid",
                    "--url", "https://example.invalid/login",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(observed["path"], path)
            self.assertEqual(observed["master"], master)
            self.assertEqual(observed["value"], value)
            self.assertIn(reference, output.getvalue())
            rendered = output.getvalue() + errors.getvalue()
            self.assertNotIn(value, rendered)
            self.assertNotIn(master, rendered)

    def test_home_verify_loads_exact_enrolled_copy_without_printing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "portable.kdbx"
            path.touch()
            garden = root / "garden.json"
            garden.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "entries": [
                            {
                                "alias": "generated-login",
                                "title": "Generated login",
                                "kind": "password",
                                "provider": "example",
                                "copies": [
                                    {
                                        "id": "portable",
                                        "type": "kdbx",
                                        "reference": "00112233445566778899aabbccddeeff",
                                    }
                                ],
                                "home": "portable",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            config = type("Config", (), {"kdbx_path": path})()
            backend = FakeBackend()
            output = io.StringIO()
            errors = io.StringIO()
            with (
                patch("secretariat.cli.Tooling.detect", return_value=self.tooling(pykeepass=True)),
                patch("secretariat.cli.load_device_config", return_value=config),
                patch("secretariat.cli.default_config_path", return_value=root / "config.json"),
                patch("secretariat.cli.backend_for", return_value=backend) as backend_factory,
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                code = cli.main(["--garden", str(garden), "home", "verify", "generated-login"])
            self.assertEqual(code, 0)
            enrolled = load_garden(garden).by_alias("generated-login")
            backend_factory.assert_called_once_with(
                enrolled.home_copy(),
                self.tooling(pykeepass=True),
                device_config=config,
            )
            self.assertIn("verified generated-login", output.getvalue())
            self.assertNotIn(FakeBackend.SENTINEL, output.getvalue() + errors.getvalue())

    def test_home_verify_refuses_non_kdbx_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "portable.kdbx"
            path.touch()
            config = type("Config", (), {"kdbx_path": path})()
            errors = io.StringIO()
            with (
                patch("secretariat.cli.Tooling.detect", return_value=self.tooling(pykeepass=True)),
                patch("secretariat.cli.load_device_config", return_value=config),
                patch("secretariat.cli.default_config_path", return_value=root / "config.json"),
                redirect_stderr(errors),
            ):
                code = cli.main(
                    ["--garden", str(EXAMPLE), "home", "verify", "example-browser-login"]
                )
            self.assertEqual(code, 2)
            self.assertIn("does not use a KDBX home copy", errors.getvalue())

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
