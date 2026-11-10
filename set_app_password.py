#!/usr/bin/env python3
"""Store a Gmail app password in .env without printing it.

Run this in a terminal:

    python3 set_app_password.py

It prompts with hidden input, removes display spaces, checks the 16-character
format, and updates the SMTP_PASS line in .env.
"""

from __future__ import annotations

import getpass
import os
import stat
import sys
from pathlib import Path

from app_password import is_app_password, normalize_app_password

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def update_env_password(path: Path, password: str) -> None:
    """Replace or append SMTP_PASS in an .env file and make it owner-only."""
    lines = path.read_text(encoding="utf-8").splitlines()
    found = False
    updated: list[str] = []

    for line in lines:
        if line.startswith("SMTP_PASS=") or line.startswith("# SMTP_PASS="):
            updated.append(f"SMTP_PASS={password}")
            found = True
        else:
            updated.append(line)

    if not found:
        updated.append(f"SMTP_PASS={password}")

    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def main() -> int:
    if not ENV_FILE.exists():
        print(f"{ENV_FILE} does not exist. Copy .env.example to .env first.", file=sys.stderr)
        return 1

    raw = getpass.getpass("Paste the 16-character Gmail app password (input hidden): ")
    if not is_app_password(raw):
        print(
            "That does not look like a Google app password. "
            "It should be 16 letters/numbers; spaces from Google's display are fine.",
            file=sys.stderr,
        )
        return 1

    update_env_password(ENV_FILE, normalize_app_password(raw))
    print("Saved SMTP_PASS to .env (16 characters, not displayed).")
    print("Next: python3 send_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
