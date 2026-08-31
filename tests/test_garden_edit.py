from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretariat.garden import load_garden
from secretariat.garden_edit import (
    GardenEditError,
    add_entry,
    attach_copy,
    detach_copy,
    set_home,
    set_login,
    set_username,
)


class GardenEditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "garden.json"
        self.path.write_text(json.dumps({"schema_version": 3, "entries": []}) + "\n", encoding="utf-8")

    def add_portable(self):
        add_entry(
            self.path,
            alias="example-login",
            title="Example login",
            username=None,
            kind="password",
            provider="example",
            copy_id="portable",
            copy_type="kdbx",
            reference="00112233445566778899aabbccddeeff",
        )

    def test_add_attach_set_home_login_and_detach(self):
        self.add_portable()
        entry = load_garden(self.path).by_alias("example-login")
        self.assertEqual(entry.home_copy().id, "portable")

        set_login(self.path, alias="example-login", url="https://example.invalid/login")
        entry = load_garden(self.path).by_alias("example-login")
        self.assertEqual(entry.links["login"], "https://example.invalid/login")

        set_username(
            self.path,
            alias="example-login",
            username="generated-user@example.invalid",
        )
        entry = load_garden(self.path).by_alias("example-login")
        self.assertEqual(entry.username, "generated-user@example.invalid")

        attach_copy(
            self.path,
            alias="example-login",
            copy_id="apple",
            copy_type="apple_passwords",
            reference="example.invalid:user@example.invalid",
            make_home=False,
        )
        entry = load_garden(self.path).by_alias("example-login")
        self.assertEqual(len(entry.copies), 2)
        self.assertEqual(entry.home_copy().id, "portable")

        set_home(self.path, alias="example-login", copy_id="apple")
        self.assertEqual(load_garden(self.path).by_alias("example-login").home_copy().id, "apple")

        detach_copy(
            self.path,
            alias="example-login",
            copy_id="portable",
            new_home=None,
        )
        entry = load_garden(self.path).by_alias("example-login")
        self.assertEqual(tuple(copy.id for copy in entry.copies), ("apple",))
        self.assertEqual(entry.home_copy().id, "apple")

    def test_invalid_login_url_never_replaces_garden(self):
        self.add_portable()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(GardenEditError, "HTTPS"):
            set_login(self.path, alias="example-login", url="http://example.invalid/login")
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_username_never_replaces_garden(self):
        self.add_portable()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(GardenEditError, "username is invalid"):
            set_username(self.path, alias="example-login", username="line one\nline two")
        self.assertEqual(self.path.read_bytes(), before)

    def test_detaching_current_home_requires_replacement(self):
        self.add_portable()
        attach_copy(
            self.path,
            alias="example-login",
            copy_id="edge",
            copy_type="edge_passwords",
            reference="example.invalid:user@example.invalid",
            make_home=False,
        )
        with self.assertRaisesRegex(GardenEditError, "requires --new-home"):
            detach_copy(
                self.path,
                alias="example-login",
                copy_id="portable",
                new_home=None,
            )

    def test_invalid_edit_never_replaces_garden(self):
        self.add_portable()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(GardenEditError, "canonical lowercase"):
            attach_copy(
                self.path,
                alias="example-login",
                copy_id="bad",
                copy_type="kdbx",
                reference="NOT-A-UUID",
                make_home=False,
            )
        self.assertEqual(self.path.read_bytes(), before)

    def test_competing_garden_revision_refuses_save(self):
        before = self.path.read_bytes()
        with patch("secretariat.garden_edit._fingerprint", return_value=(0, 0, b"different")):
            with self.assertRaisesRegex(GardenEditError, "diverged"):
                add_entry(
                    self.path,
                    alias="example-login",
                    title="Example login",
                    username=None,
                    kind="password",
                    provider="example",
                    copy_id="portable",
                    copy_type="kdbx",
                    reference="00112233445566778899aabbccddeeff",
                )
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
