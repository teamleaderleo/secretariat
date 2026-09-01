from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from secretariat import app, home_cli
from secretariat.config import DeviceConfig
from secretariat.home_state import PortableHomeStatus


class HomeCLIStatusTests(unittest.TestCase):
    def status(self):
        return PortableHomeStatus(
            state="available_unlocked",
            kdbx_library="available",
            kdbx_path="configured",
            kdbx_file="available",
            agent="unlocked",
            idle_seconds_remaining=500,
            ttl_seconds_remaining=3000,
        )

    def test_json_status_is_value_free_and_includes_agent_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config_path.write_text("{}\n", encoding="utf-8")
            output = io.StringIO()
            with (
                patch("secretariat.home_cli.default_config_path", return_value=config_path),
                patch("secretariat.home_cli.load_device_config", return_value=DeviceConfig()),
                patch("secretariat.home_cli.inspect_portable_home", return_value=self.status()),
                redirect_stdout(output),
            ):
                code = home_cli.main(["--json", "home", "status"])
            self.assertEqual(code, 0)
            document = json.loads(output.getvalue())
            self.assertEqual(document["state"], "available_unlocked")
            self.assertEqual(document["agent"], "unlocked")
            self.assertEqual(document["idle_seconds_remaining"], 500)
            self.assertNotIn("password", output.getvalue().casefold())

    def test_non_status_home_command_delegates_to_core_cli(self):
        arguments = ["home", "verify", "generated-login"]
        with patch("secretariat.home_cli.core_cli.main", return_value=9) as core:
            self.assertEqual(home_cli.main(arguments), 9)
        core.assert_called_once_with(arguments)

    def test_top_level_dispatch_routes_home_to_status_layer(self):
        arguments = ["--garden", "/private/generated-garden.json", "home", "status"]
        with patch("secretariat.app.home_cli.main", return_value=8) as home:
            self.assertEqual(app.main(arguments), 8)
        home.assert_called_once_with(arguments)


if __name__ == "__main__":
    unittest.main()
