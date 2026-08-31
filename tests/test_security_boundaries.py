from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from secretariat.audit import audit_repository
from secretariat.backends import BackendError, SecretServiceBackend, Tooling, backend_for, copy_paste_once
from secretariat.garden import Copy


class SecurityBoundaryTests(unittest.TestCase):
    def test_indexed_copy_refuses_value_access(self):
        with self.assertRaisesRegex(BackendError, "indexed only"):
            backend_for(Copy("apple", "apple_passwords", "example.invalid"), Tooling(None, None, None))

    def test_secret_service_store_keeps_value_out_of_argv(self):
        copy = Copy("secret", "secret_service", "fixture")
        sentinel = "generated-sentinel-for-stdin-only"
        completed = type("Completed", (), {"returncode": 0})()
        with patch("secretariat.backends.subprocess.run", return_value=completed) as run:
            SecretServiceBackend("/reviewed/secret-tool").store(copy, sentinel, "Fixture")
        self.assertNotIn(sentinel, " ".join(run.call_args.args[0]))
        self.assertEqual(run.call_args.kwargs["input"], sentinel)

    def test_paste_once_uses_stdin(self):
        sentinel = "generated-sentinel-for-clipboard"
        completed = type("Completed", (), {"returncode": 0})()
        with patch("secretariat.backends.subprocess.run", return_value=completed) as run:
            copy_paste_once(sentinel, Tooling(None, "/reviewed/wl-copy", None))
        self.assertEqual(run.call_args.kwargs["input"], sentinel)
        self.assertNotIn(sentinel, " ".join(run.call_args.args[0]))

    def test_audit_includes_untracked_files_without_printing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
            sentinel = "gh" + "p_" + ("A" * 24)
            (root / "untracked.txt").write_text(sentinel + "\n", encoding="utf-8")
            findings = audit_repository(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].rule, "github-token")
            self.assertNotIn(sentinel, repr(findings))


if __name__ == "__main__":
    unittest.main()
