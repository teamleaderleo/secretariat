"""Conservative repository leak checks."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


SECRET_PATTERNS = (
    (
        "private-key",
        re.compile(r"-----BEGIN " + r"(?:OPENSSH |RSA |EC )?PRIVATE KEY-----"),
    ),
    ("github-token", re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b")),
    ("generic-bearer", re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{16,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
)


@dataclass(frozen=True)
class AuditFinding:
    path: str
    line: int
    rule: str


class AuditError(RuntimeError):
    pass


def candidate_files(root: Path) -> tuple[Path, ...]:
    git = shutil.which("git")
    if git is None:
        raise AuditError("Git executable is unavailable")
    result = subprocess.run(
        [git, "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        raise AuditError("tracked-file inventory could not be read")
    paths = []
    for raw in result.stdout.split(b"\0"):
        if raw:
            try:
                relative = Path(raw.decode("utf-8", "strict"))
            except UnicodeDecodeError as error:
                raise AuditError("repository contains a non-UTF-8 path") from error
            path = root / relative
            if path.is_symlink() or not path.is_file():
                continue
            paths.append(path)
    return tuple(paths)


def audit_repository(root: Path) -> tuple[AuditFinding, ...]:
    findings: list[AuditFinding] = []
    for path in candidate_files(root):
        try:
            if path.stat().st_size > 1_048_576:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(AuditFinding(relative, line_number, rule))
    return tuple(findings)
