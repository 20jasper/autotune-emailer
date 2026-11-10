#!/usr/bin/env python3

import hashlib
import json
import re
import statistics
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from send_report import load_env

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


class Stats(TypedDict):
    readings: int
    mean: float
    sd: float
    cv: float
    ea1c: float
    gmi: float
    tir: float
    tbr: float
    tar: float


def auth_header(env: dict[str, str]) -> dict[str, str]:
    secret = env.get("NS_API_SECRET", "")
    if not secret:
        return {}
    if re.fullmatch(r"[a-fA-F0-9]{40}", secret):
        return {"api-secret": secret.lower()}
    return {"api-secret": hashlib.sha1(secret.encode()).hexdigest()}


def fetch_entries(env: dict[str, str], params: dict[str, str | int]) -> list[dict[str, Any]]:
    base = env["NS_HOST"].rstrip("/")
    url = f"{base}/api/v1/entries/sgv.json?" + urlencode(params)
    token = env.get("NS_TOKEN", "")
    if token and not env.get("NS_API_SECRET"):
        url += "&" + urlencode({"token": token})
    request = Request(url, headers={"Accept": "application/json", **auth_header(env)})
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def calculate(entries: list[dict[str, Any]]) -> Stats | None:
    values: list[float] = []
    for entry in entries:
        try:
            value = float(entry["sgv"])
        except KeyError, TypeError, ValueError:
            continue
        if 39 <= value <= 600:
            values.append(value)

    if not values:
        return None

    mean = statistics.fmean(values)
    sd = statistics.pstdev(values)
    return {
        "readings": len(values),
        "mean": mean,
        "sd": sd,
        "cv": sd / mean * 100,
        "ea1c": (mean + 46.7) / 28.7,
        "gmi": 3.31 + 0.02392 * mean,
        "tir": sum(70 <= value <= 180 for value in values) / len(values) * 100,
        "tbr": sum(value < 70 for value in values) / len(values) * 100,
        "tar": sum(value > 180 for value in values) / len(values) * 100,
    }


def render(stats: Stats, start: datetime, end: datetime) -> str:
    return "\n".join(
        [
            "Nightscout CGM stats",
            f"Window: {start:%Y-%m-%d %H:%M} -> {end:%Y-%m-%d %H:%M} {start.tzinfo}",
            f"Readings: {stats['readings']}",
            f"Mean glucose: {stats['mean']:.1f} mg/dL",
            f"SD: {stats['sd']:.1f} mg/dL | CV: {stats['cv']:.1f}%",
            f"eA1c (ADAG): {stats['ea1c']:.2f}%",
            f"GMI: {stats['gmi']:.2f}%",
            f"Time in range 70-180: {stats['tir']:.1f}%",
            f"Below 70: {stats['tbr']:.1f}%",
            f"Above 180: {stats['tar']:.1f}%",
            "",
            "eA1c and GMI are estimates from CGM, not lab results.",
        ]
    )


def main() -> int:
    env = load_env(ROOT / ".env")
    tz = ZoneInfo(env.get("TZ", "UTC"))
    days = int(env.get("AUTOTUNE_DAYS", "6"))

    today = datetime.now(tz).date()
    end_date = today - timedelta(days=1)
    start_date = end_date - timedelta(days=days)
    start = datetime.combine(start_date, time(4, 0), tzinfo=tz)
    end = datetime.combine(end_date + timedelta(days=1), time(4, 0), tzinfo=tz)

    entries = fetch_entries(
        env,
        {
            "find[date][$gte]": int(start.timestamp() * 1000),
            "find[date][$lte]": int(end.timestamp() * 1000),
            "count": 50000,
        },
    )
    stats = calculate(entries)
    if stats is None:
        print("No CGM data for the window.")
        return 0

    text = render(stats, start, end)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "cgm-stats.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
