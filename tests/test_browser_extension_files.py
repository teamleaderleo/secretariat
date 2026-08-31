from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "browser" / "extension"


class BrowserExtensionFileTests(unittest.TestCase):
    def test_manifest_has_narrow_permissions_and_no_persistent_content_script(self):
        manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(set(manifest["permissions"]), {"activeTab", "nativeMessaging", "scripting"})
        self.assertNotIn("host_permissions", manifest)
        self.assertNotIn("content_scripts", manifest)

    def test_service_worker_uses_native_host_without_extension_storage(self):
        script = (EXTENSION / "service_worker.js").read_text(encoding="utf-8")
        request = (EXTENSION / "native_request.mjs").read_text(encoding="utf-8")
        self.assertIn("sendNativeRequest(chrome.runtime, HOST_NAME, request)", script)
        self.assertIn("runtime.sendNativeMessage(hostName, request", request)
        self.assertIn("chrome.tabs.get(tab.id)", script)
        self.assertNotIn("chrome.storage", script)
        self.assertNotIn("chrome.storage", request)
        self.assertNotIn("localStorage", script)
        self.assertNotIn("localStorage", request)

    def test_popup_inserts_metadata_as_text(self):
        script = (EXTENSION / "popup.js").read_text(encoding="utf-8")
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
