from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from secretariat.backends import (
    BackendError,
    KDBXBackend,
    _encrypted_fingerprint,
    add_kdbx_entry,
    create_kdbx_home,
)
from secretariat.garden import Copy
from secretariat.kdbx_agent import UnlockedKDBXSession

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

    def test_unlocked_session_reuses_open_database_and_tracks_its_own_saves(self):
        session = UnlockedKDBXSession.open(self.path, self.master_password)
        self.addCleanup(session.close)
        self.assertEqual(session.load(self.reference), "generated-old-value")
        session.store(self.reference, "generated-agent-value")
        self.assertEqual(session.load(self.reference), "generated-agent-value")

        database = PyKeePass(str(self.path), password=self.master_password)
        entry = database.find_entries(uuid=uuid.UUID(hex=self.reference), first=True)
        self.assertEqual(entry.password, "generated-agent-value")
        self.assertGreaterEqual(len(entry.history), 1)

    def test_unlocked_session_invalidates_after_external_encrypted_revision(self):
        session = UnlockedKDBXSession.open(self.path, self.master_password)
        competing = Path(self.temporary.name) / "competing.kdbx"
        shutil.copy2(self.path, competing)
        competing_database = PyKeePass(str(competing), password=self.master_password)
        entry = competing_database.find_entries(uuid=uuid.UUID(hex=self.reference), first=True)
        entry.password = "generated-competing-value"
        competing_database.save()
        shutil.copy2(competing, self.path)

        with self.assertRaisesRegex(BackendError, "changed since unlock"):
            session.load(self.reference)
        with self.assertRaisesRegex(BackendError, "session is locked"):
            session.load(self.reference)

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

    def test_create_home_and_add_entry_round_trip(self):
        home = Path(self.temporary.name) / "new-home.kdbx"
        create_kdbx_home(home, self.master_password)
        self.assertTrue(home.is_file())
        self.assertEqual(home.stat().st_mode & 0o777, 0o600)

        reference = add_kdbx_entry(
            home,
            lambda: self.master_password,
            title="Added fixture",
            username="generated-user@example.invalid",
            url="https://example.invalid/login",
            value="generated-added-value",
        )
        self.assertRegex(reference, r"^[0-9a-f]{32}$")

        backend = KDBXBackend(home, lambda: self.master_password)
        self.assertEqual(
            backend.load(Copy("portable", "kdbx", reference)),
            "generated-added-value",
        )

    def test_create_home_refuses_existing_file(self):
        with self.assertRaisesRegex(BackendError, "already exists"):
            create_kdbx_home(self.path, self.master_password)


if __name__ == "__main__":
    unittest.main()
