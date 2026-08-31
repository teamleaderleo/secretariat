from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from secretariat.backends import BackendError, KDBXBackend, _encrypted_fingerprint
from secretariat.garden import Copy

try:
    from pykeepass import PyKeePass, create_database
except ImportError:
    PyKeePass = None
    create_database = None


@unittest.skipUnless(create_database is not None, "optional pykeepass dependency is not installed")
class KDBXBackendIntegrationTests(unittest.TestCase):
    master_password = "generated-database-password"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "fixture.kdbx"
        database = create_database(str(self.path), password=self.master_password)
        entry = database.add_entry(
            database.root_group,
            "Fixture",
            "generated-user",
            "generated-old-value",
            url="https://example.invalid",
        )
        database.save()
        self.reference = entry.uuid.hex.lower()
        self.copy = Copy("portable", "kdbx", self.reference)
        self.backend = KDBXBackend(self.path, lambda: self.master_password)

    def test_exact_uuid_load_and_update_preserve_uuid_and_history(self):
        self.assertEqual(self.backend.load(self.copy), "generated-old-value")
        self.backend.store(self.copy, "generated-new-value", "Fixture")

        database = PyKeePass(str(self.path), password=self.master_password)
        entry = database.find_entries(uuid=uuid.UUID(hex=self.reference), first=True)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.uuid.hex.lower(), self.reference)
        self.assertEqual(entry.password, "generated-new-value")
        self.assertGreaterEqual(len(entry.history), 1)
        self.assertEqual(entry.history[-1].password, "generated-old-value")

    def test_noncanonical_reference_fails_before_lookup(self):
        bad = Copy("portable", "kdbx", self.reference.upper())
        with self.assertRaisesRegex(BackendError, "canonical lowercase"):
            self.backend.load(bad)

    def test_competing_revision_refuses_write(self):
        baseline = _encrypted_fingerprint(self.path)
        changed = (baseline[0], baseline[1] + 1, baseline[2])
        with patch("secretariat.backends._encrypted_fingerprint", side_effect=[baseline, changed]):
            with self.assertRaisesRegex(BackendError, "diverged"):
                self.backend.store(self.copy, "generated-conflicting-value", "Fixture")

        database = PyKeePass(str(self.path), password=self.master_password)
        entry = database.find_entries(uuid=uuid.UUID(hex=self.reference), first=True)
        self.assertEqual(entry.password, "generated-old-value")


if __name__ == "__main__":
    unittest.main()
