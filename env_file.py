from __future__ import annotations

import os
import re
from pathlib import Path

Env = dict[str, str]


def load_env(path: Path) -> Env:
    values: Env = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            match = re.search(r"\s+#", value)
            if match:
                value = value[: match.start()].strip()

        if key:
            values[key] = value

    return values


def setting(env: Env, key: str, default: str = "") -> str:
    return os.environ.get(key) or env.get(key) or default


def truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
