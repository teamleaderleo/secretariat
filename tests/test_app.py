from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from secretariat import app
from secretariat.garden import load_garden


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "garden.example.json"
EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


class AppDispatchTests(unittest.TestCase):
    def test_existing_commands_still_delegate_to_core_cli(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = app.main(["--garden", str(EXAMPLE), "find", "chrome"])
        self.assertEqual(code, 0)
        self.assertIn("example-browser-login", output.getvalue())

    def test_browser_manifest_dispatches_without_a_garden(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = app.main(
                [
                    "browser",
                    "manifest",
                    "--extension-id",
                    EXTENSION_ID,
                    "--host-path",
                    "/usr/local/bin/secretariat-native-host",
                ]
            )
        self.assertEqual(code, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["name"], "com.secretariat.browser")
        self.assertEqual(
            document["allowed_origins"],
            [f"chrome-extension://{EXTENSION_ID}/"],
        )

    def test_garden_add_set_login_and_attach_use_private_garden_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "garden.json"
            path.write_text(json.dumps({"schema_version": 3, "entries": []}) + "\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                code = app.main([
                    "--garden", str(path),
                    "garden", "add",
                    "--alias", "example-login",
                    "--title", "Example login",
                    "--kind", "password",
                    "--provider", "example",
                    "--copy-id", "portable",
                    "--copy-type", "kdbx",
                    "--reference", "00112233445566778899aabbccddeeff",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(load_garden(path).by_alias("example-login").home_copy().id, "portable")

            output = io.StringIO()
            with redirect_stdout(output):
                code = app.main([
                    "--garden", str(path),
                    "garden", "set-login",
                    "--alias", "example-login",
                    "--url", "https://example.invalid/login",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(
                load_garden(path).by_alias("example-login").links["login"],
                "https://example.invalid/login",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                code = app.main([
                    "--garden", str(path),
                    "garden", "attach",
                    "--alias", "example-login",
                    "--copy-id", "apple",
                    "--copy-type", "apple_passwords",
                    "--reference", "example.invalid:user@example.invalid",
                    "--home",
                ])
            self.assertEqual(code, 0)
            entry = load_garden(path).by_alias("example-login")
            self.assertEqual(len(entry.copies), 2)
            self.assertEqual(entry.home_copy().id, "apple")

    def test_garden_detach_home_refuses_without_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "garden.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "entries": [
                            {
                                "alias": "example-login",
                                "title": "Example login",
                                "kind": "password",
                                "provider": "example",
                                "copies": [
                                    {"id": "portable", "type": "kdbx", "reference": "00112233445566778899aabbccddeeff"},
                                    {"id": "edge", "type": "edge_passwords", "reference": "example.invalid:user@example.invalid"},
                                ],
                                "home": "portable",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            errors = io.StringIO()
            with redirect_stderr(errors):
                code = app.main([
                    "--garden", str(path),
                    "garden", "detach",
                    "--alias", "example-login",
                    "--copy-id", "portable",
                ])
            self.assertEqual(code, 2)
            self.assertIn("requires --new-home", errors.getvalue())
            self.assertEqual(load_garden(path).by_alias("example-login").home_copy().id, "portable")


if __name__ == "__main__":
    unittest.main()
