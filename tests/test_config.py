from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretariat.config import DeviceConfigError, load_device_config


class DeviceConfigTests(unittest.TestCase):
    def test_relative_kdbx_path_resolves_from_config_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"kdbx": {"path": "Drive/secretariat.kdbx"}}), encoding="utf-8")
            loaded = load_device_config(config)
            self.assertEqual(loaded.kdbx_path, root / "Drive" / "secretariat.kdbx")

    def test_environment_path_overrides_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_text(json.dumps({"kdbx": {"path": "file.kdbx"}}), encoding="utf-8")
            override = root / "override.kdbx"
            with patch.dict(os.environ, {"SECRETARIAT_KDBX_PATH": str(override)}):
                loaded = load_device_config(config)
            self.assertEqual(loaded.kdbx_path, override)

    def test_unknown_config_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps({"password": "generated-fixture"}), encoding="utf-8")
            with self.assertRaisesRegex(DeviceConfigError, "unknown field"):
                load_device_config(config)


if __name__ == "__main__":
    unittest.main()
