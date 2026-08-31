from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from secretariat import app


EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"


class BrowserCliTests(unittest.TestCase):
    def test_global_json_config_snippet(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = app.main(["--json", "browser", "config-snippet", "--extension-id", EXTENSION_ID])
        self.assertEqual(code, 0)
        document = json.loads(output.getvalue())
        self.assertEqual(
            document["browser"]["allowed_extension_origins"],
            [f"chrome-extension://{EXTENSION_ID}/"],
        )

    def test_manifest_requires_absolute_host_path(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = app.main(
                [
                    "browser",
                    "manifest",
                    "--extension-id",
                    EXTENSION_ID,
                    "--host-path",
                    "relative/secretariat-native-host",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("absolute path", errors.getvalue())

    def test_extension_id_is_strict(self):
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = app.main(
                [
                    "browser",
                    "config-snippet",
                    "--extension-id",
                    "not-an-extension-id",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("extension id", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
