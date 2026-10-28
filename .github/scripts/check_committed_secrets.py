"""Fail when a tracked file could carry a real credential (Security audit F-01, 22 Oct 2026).

gitleaks scans text, but the audit report that leaked the production database password was a PDF.
Two rules, run in CI and usable locally (``python .github/scripts/check_committed_secrets.py``):

1. A connection URL with an embedded password (postgres, redis, rediss, mysql, mongodb, amqp)
   may only point at a local host or use a known development placeholder password.
2. Binary documents (PDF, Office) may only be committed when listed in ALLOWED_DOCUMENTS after a
   human has checked them for credentials. Audit reports belong outside the repository.
"""

import re
import subprocess
import sys
from urllib.parse import urlsplit

ALLOWED_DOCUMENTS = {
    "Docs/Abhijatri Project Gantt — CSE 3102.xlsx",
    "Docs/Abhijatri_Project_Proposal.pdf",
    "Security_Abhijatra.pdf",
}
DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres", "redis", "h"}
PLACEHOLDER_PASSWORDS = {"abhijatri_dev", "abhijatri_ci", "pw", "p", "password", "<password>"}
URL = re.compile(
    r"\b(?:postgres(?:ql)?(?:\+psycopg2?)?|rediss?|mysql|mongodb(?:\+srv)?|amqps?)://"
    r"[^\s'\"<>@/:]+:[^\s'\"<>@/]+@[^\s'\"<>/:]+"
)


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode("utf-8")
    return [name for name in output.split("\0") if name]


def problems() -> list[str]:
    found: list[str] = []
    for name in tracked_files():
        if name.lower().endswith(DOCUMENT_SUFFIXES):
            if name not in ALLOWED_DOCUMENTS:
                found.append(f"{name}: binary document not in ALLOWED_DOCUMENTS (check it for credentials first)")
            continue
        try:
            with open(name, encoding="utf-8") as handle:
                text = handle.read()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in URL.finditer(line):
                parts = urlsplit(match.group(0))
                if (parts.hostname or "") in LOCAL_HOSTS or parts.password in PLACEHOLDER_PASSWORDS:
                    continue
                found.append(f"{name}:{line_number}: connection URL with a password for host {parts.hostname}")
    return found


if __name__ == "__main__":
    issues = problems()
    for issue in issues:
        print(f"::error::{issue}")
    if issues:
        print("Remove the credential (rotate it if it was ever pushed) or use a placeholder.")
    sys.exit(1 if issues else 0)
