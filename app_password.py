"""Helpers for Google-style 16-character app passwords."""

from __future__ import annotations

import re

_APP_PASSWORD = re.compile(r"[A-Za-z0-9]{16}")


def normalize_app_password(value: str) -> str:
    """Remove display spaces from a 16-character app password, if it matches."""
    compact = re.sub(r"\s+", "", value)
    return compact if _APP_PASSWORD.fullmatch(compact) else value


def is_app_password(value: str) -> bool:
    """Return True when the value is 16 alphanumeric characters, ignoring spaces."""
    return _APP_PASSWORD.fullmatch(re.sub(r"\s+", "", value)) is not None
