#!/usr/bin/env python3

import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"

TH_STYLE = "border:1px solid #ddd;padding:6px 8px;background:#f3f4f6;"
TD_STYLE = "border:1px solid #ddd;padding:6px 8px;"
TABLE_STYLE = "border-collapse:collapse;border:1px solid #ddd;font-size:14px;"
PRE_STYLE = "font-size:12px;background:#f7f7f7;padding:8px;border:1px solid #eee;"


class Row(TypedDict):
    time: str
    pump: float | None
    autotune: float | None
    days: int | None


class Report(TypedDict):
    isf: tuple[float, float] | None
    cr: tuple[float, float] | None
    rows: list[Row]


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            env[key] = value
    return env


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def parse_report(text: str) -> Report:
    isf: tuple[float, float] | None = None
    cr: tuple[float, float] | None = None
    rows: list[Row] = []

    for line in text.splitlines():
        if line.startswith("ISF"):
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 3 and cols[1] and cols[2]:
                isf = (float(cols[1]), float(cols[2]))
        elif line.startswith("Carb Ratio"):
            cols = [c.strip() for c in line.split("|")]
            if len(cols) >= 3 and cols[1] and cols[2]:
                cr = (float(cols[1]), float(cols[2]))
        else:
            match = re.match(r"^\s*(\d{2}:\d{2})\s*\|(.*)$", line)
            if match:
                cols = [c.strip() for c in match.group(2).split("|")]
                rows.append(
                    {
                        "time": match.group(1),
                        "pump": float(cols[0]) if cols and cols[0] else None,
                        "autotune": float(cols[1]) if len(cols) > 1 and cols[1] else None,
                        "days": int(cols[2]) if len(cols) > 2 and cols[2] else None,
                    }
                )

    return {"isf": isf, "cr": cr, "rows": rows}


def parse_window(log: str) -> str:
    start = end = ""
    for match in re.finditer(r"^start_date:\s*(\S+)", log, re.MULTILINE):
        start = match.group(1)
    for match in re.finditer(r"^end_date:\s*(\S+)", log, re.MULTILINE):
        end = match.group(1)
    return f"{start} to {end}" if start and end else ""


def parse_stats(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def pct(current: float | None, new: float | None) -> float | None:
    if current is None or new is None or current == 0:
        return None
    return (new - current) / current * 100


def fmt_pct(value: float | None) -> str:
    return f"{value:+.1f}%" if value is not None else "—"


def color(value: float | None) -> str:
    if value is None:
        return "#666"
    if value >= 20 or value <= -30:
        return "#b00020"
    if abs(value) >= 10:
        return "#9a6700"
    return "#1a7f37"


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f'<th align="left" style="{TH_STYLE}">{escape(h)}</th>' for h in headers)
    body = "".join(
        "<tr>" + "".join(f'<td style="{TD_STYLE}">{value}</td>' for value in row) + "</tr>"
        for row in rows
    )
    return f'<table style="{TABLE_STYLE}">{head}{body}</table>'


def stats_rows(text: str) -> list[list[str]]:
    values = parse_stats(text)
    rows: list[list[str]] = []
    for key in ("Readings", "Mean glucose"):
        if key in values:
            rows.append([key, escape(values[key])])

    sd = values.get("SD", "")
    if "|" in sd:
        sd_value, cv_value = [part.strip() for part in sd.split("|", 1)]
        rows.append(["SD", escape(sd_value)])
        rows.append(["CV", escape(cv_value)])
    elif sd:
        rows.append(["SD", escape(sd)])

    for key in (
        "eA1c (ADAG)",
        "GMI",
        "Time in range 70-180",
        "Below 70",
        "Above 180",
    ):
        if key in values:
            rows.append([key, escape(values[key])])
    return rows


def render_html(report: Report, stats: str, raw_text: str, window: str) -> str:
    parts = [
        '<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#333;">',
        "<h2>Nightscout Autotune report</h2>",
    ]
    if window:
        parts.append(f"<p>{escape(window)}</p>")

    params: list[list[str]] = []
    if report["isf"]:
        current, new = report["isf"]
        change = pct(current, new)
        params.append(
            [
                "ISF",
                f"{current:.2f}",
                f"{new:.2f}",
                f'<span style="color:{color(change)};">{fmt_pct(change)}</span>',
            ]
        )
    if report["cr"]:
        current, new = report["cr"]
        change = pct(current, new)
        params.append(
            [
                "Carb ratio",
                f"{current:.2f}",
                f"{new:.2f}",
                f'<span style="color:{color(change)};">{fmt_pct(change)}</span>',
            ]
        )
    if params:
        parts.append("<h3>ISF and carb ratio</h3>")
        parts.append(table(["Parameter", "Current", "Autotune", "Change"], params))

    current_value: float | None = None
    current_at: dict[str, float] = {}
    for row in sorted(report["rows"], key=lambda item: item["time"]):
        if row["pump"] is not None:
            current_value = row["pump"]
        if row["time"].endswith(":00") and current_value is not None:
            current_at[row["time"]] = current_value

    basal: list[list[str]] = []
    for row in report["rows"]:
        if not row["time"].endswith(":00") or row["autotune"] is None:
            continue
        current_rate = current_at.get(row["time"])
        new_rate = row["autotune"]
        change = pct(current_rate, new_rate)
        days = row["days"] if row["days"] is not None else 0
        basal.append(
            [
                row["time"],
                f"{current_rate:.3f}" if current_rate is not None else "—",
                f"{new_rate:.3f}",
                f'<span style="color:{color(change)};">{fmt_pct(change)}</span>',
                str(days),
            ]
        )
    if basal:
        parts.append("<h3>Basal recommendations</h3>")
        parts.append(table(["Time", "Current", "Autotune", "Change", "Days missing"], basal))

    cgm = stats_rows(stats)
    if cgm:
        parts.append("<h3>CGM stats</h3>")
        parts.append(table(["Metric", "Value"], cgm))
        parts.append(
            '<p style="color:#666;">eA1c and GMI are estimates from CGM, not lab results.</p>'
        )

    if raw_text:
        parts.append("<h3>Raw text report</h3>")
        parts.append(f'<pre style="{PRE_STYLE}">{escape(raw_text)}</pre>')

    parts.append("</body></html>")
    return "".join(parts)


def send(host: str, port: int, user: str, password: str, message: EmailMessage) -> None:
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls(context=ssl.create_default_context())
        server.login(user, re.sub(r"\s+", "", password))
        server.send_message(message)


def main() -> int:
    status = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    env = load_env(ROOT / ".env")
    text = read(REPORTS / "autotune_recommendations.log")
    html_report = read(REPORTS / "autotune_recommendations.html")
    profile = read(REPORTS / "tuned-profile.json")
    stats = read(REPORTS / "cgm-stats.txt")
    log = read(REPORTS / "last-run.log")
    failed = status != 0 or not text
    window = parse_window(log)

    user = env.get("SMTP_USER", "")
    password = env.get("SMTP_PASS", "")
    to = env.get("SMTP_TO", "")
    sender = env.get("SMTP_FROM") or user

    if not user or not password or not to or not sender:
        print("Email is not configured.")
        return 0

    message = EmailMessage()
    if failed:
        message["Subject"] = "Nightscout Autotune failed"
    elif window:
        message["Subject"] = f"Nightscout Autotune report ({window})"
    else:
        message["Subject"] = "Nightscout Autotune report"
    message["From"] = sender
    message["To"] = to

    if failed:
        message.set_content("Autotune failed.\n\n" + "\n".join(log.splitlines()[-40:]))
        if log:
            message.add_attachment(
                log.encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename="autotune-last-run.log",
            )
    else:
        message.set_content(text + ("\n\n" + stats if stats else ""))
        message.add_alternative(
            render_html(parse_report(text), stats, text, window),
            subtype="html",
        )
        if html_report:
            message.add_attachment(
                html_report.encode("utf-8"),
                maintype="text",
                subtype="html",
                filename="autotune_recommendations.html",
            )
        if profile:
            message.add_attachment(
                profile.encode("utf-8"),
                maintype="application",
                subtype="json",
                filename="tuned-profile.json",
            )
        if stats:
            message.add_attachment(
                stats.encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename="cgm-stats.txt",
            )

    try:
        send(
            env.get("SMTP_HOST", "smtp.gmail.com"),
            int(env.get("SMTP_PORT", "587")),
            user,
            password,
            message,
        )
    except Exception as error:
        print(f"Email failed: {error}")
        return 1
    print("Email sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
