#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import smtplib
import ssl
import sys
from contextlib import suppress
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

from app_password import normalize_app_password
from env_file import Env, load_env, setting, truthy

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
REPORTS = ROOT / "reports"

Profile = dict[str, Any]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as error:
        print(f"Could not read {path}: {error}", file=sys.stderr)
        return ""


def parse_window(log: str) -> tuple[str, str]:
    start = end = ""
    for match in re.finditer(r"^start_date:\s*(\S+)", log, re.MULTILINE):
        start = match.group(1)
    for match in re.finditer(r"^end_date:\s*(\S+)", log, re.MULTILINE):
        end = match.group(1)
    return start, end


def load_tuned_profile() -> Profile | None:
    path = REPORTS / "tuned-profile.json"
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast(Profile, data) if isinstance(data, dict) else None


def loop_settings_summary(profile: Profile | None) -> str:
    if not profile:
        return ""

    isf_profile = profile.get("isfProfile")
    sensitivities: list[dict[str, Any]] = []
    if isinstance(isf_profile, dict):
        raw_sensitivities = isf_profile.get("sensitivities")
        if isinstance(raw_sensitivities, list):
            sensitivities = [item for item in raw_sensitivities if isinstance(item, dict)]

    isf = sensitivities[0].get("sensitivity") if sensitivities else None
    carb_ratio = profile.get("carb_ratio")
    dia = profile.get("dia")

    lines = [
        "SUGGESTED LOOP THERAPY SETTINGS (review before applying)",
        "",
        f"DIA:         {dia} h",
        f"ISF:         {isf} mg/dL/U",
        f"Carb ratio:  {carb_ratio} g/U",
        "",
        "Basal rates:",
    ]

    basal_profile = profile.get("basalprofile")
    basal_items: list[dict[str, Any]] = []
    if isinstance(basal_profile, list):
        basal_items = [item for item in basal_profile if isinstance(item, dict)]

    for item in basal_items:
        start = str(item.get("start", ""))[:5]
        rate = item.get("rate")
        lines.append(f"  {start}  {rate} U/hr")

    lines += [
        "",
        "Autotune outputs up to 3 decimals. Round to what your pump/Loop",
        "accepts (often 0.01 or 0.05 U/hr).",
        "",
        "These are Autotune suggestions, not medical advice. Loop does not",
        "import this automatically; enter accepted changes manually in",
        "Loop -> Settings -> Therapy Settings. Check the Days Missing column",
        "in the report, and change one thing at a time.",
    ]
    return "\n".join(lines)


def build_message(env: Env, status: int) -> EmailMessage | None:
    log = read_text(REPORTS / "last-run.log")
    text_report = read_text(REPORTS / "autotune_recommendations.log")
    html_report = read_text(REPORTS / "autotune_recommendations.html")
    start, end = parse_window(log)
    window = f"{start} to {end}" if start and end else "latest run"

    failed = status != 0 or not text_report
    subject = (
        f"Nightscout Autotune FAILED ({window})"
        if failed
        else f"Nightscout Autotune report ({window})"
    )

    if failed:
        tail = "\n".join(log.strip().splitlines()[-40:]) if log else "(no log available)"
        body_lines = [
            "Nightscout Autotune did not finish successfully.",
            "",
            f"Exit status: {status}",
            f"Window: {window}" if start and end else "",
            "",
            "Last part of the run log:",
            "",
            tail,
            "",
            "The full log is attached if it exists.",
        ]
    else:
        summary = loop_settings_summary(load_tuned_profile())
        body_lines = [
            "Nightscout Autotune finished.",
            "",
            f"Window: {window}",
            "",
            summary,
            "",
            "The HTML report is included below. The full text report and the",
            "tuned OpenAPS profile are attached.",
            "",
            "Do not apply a large change at once. Review the report, especially",
            "the Days Missing column, before changing anything in Loop.",
        ]

    message = EmailMessage()
    message["Subject"] = subject

    smtp_from = setting(env, "SMTP_FROM") or setting(env, "SMTP_USER")
    smtp_to = setting(env, "SMTP_TO")
    if not smtp_from or not smtp_to:
        return None

    message["From"] = smtp_from
    message["To"] = ", ".join(part.strip() for part in smtp_to.split(",") if part.strip())
    message.set_content("\n".join(body_lines))

    if not failed and html_report:
        message.add_alternative(html_report, subtype="html")

    if not failed:
        if text_report:
            message.add_attachment(
                text_report.encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename="autotune_recommendations.log",
            )
        profile_text = read_text(REPORTS / "tuned-profile.json")
        if profile_text:
            message.add_attachment(
                profile_text.encode("utf-8"),
                maintype="application",
                subtype="json",
                filename="tuned-profile.json",
            )
    elif log:
        message.add_attachment(
            log.encode("utf-8"),
            maintype="text",
            subtype="plain",
            filename="autotune-last-run.log",
        )

    return message


def smtp_port(env: Env) -> int:
    use_ssl = truthy(setting(env, "SMTP_SSL", "false"))
    raw = setting(env, "SMTP_PORT", "465" if use_ssl else "587")
    try:
        return int(raw)
    except ValueError as error:
        raise ValueError(f"SMTP_PORT must be a number, got {raw!r}") from error


def send_message(env: Env, message: EmailMessage) -> None:
    host = setting(env, "SMTP_HOST")
    if not host:
        raise ValueError("SMTP_HOST is not set.")

    port = smtp_port(env)
    user = setting(env, "SMTP_USER")
    password = normalize_app_password(setting(env, "SMTP_PASS"))
    use_ssl = truthy(setting(env, "SMTP_SSL", "false"))
    use_starttls = truthy(setting(env, "SMTP_STARTTLS", "true")) and not use_ssl

    context = ssl.create_default_context()
    server: smtplib.SMTP
    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if use_starttls:
            server.starttls(context=context)

    try:
        if user:
            server.login(user, password)
        server.send_message(message)
    finally:
        with suppress(Exception):
            server.quit()

    print(f"Email sent to {message['To'] or ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Email the latest Autotune report.")
    parser.add_argument(
        "--status",
        type=int,
        default=0,
        help="Exit status of the Autotune run (non-zero sends a failure email).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write reports/email-preview.eml instead of sending.",
    )
    args = parser.parse_args()

    env = load_env(ENV_FILE)
    if args.dry_run:
        if not env.get("SMTP_HOST"):
            env["SMTP_HOST"] = "preview"
        if not env.get("SMTP_FROM"):
            env["SMTP_FROM"] = "you@example.com"
        if not env.get("SMTP_TO"):
            env["SMTP_TO"] = "you@example.com"

    message = build_message(env, args.status)
    if message is None:
        if not setting(env, "SMTP_HOST") or not setting(env, "SMTP_TO"):
            print("Email is not configured (set SMTP_HOST and SMTP_TO in .env). Skipping.")
            return 0
        print("Email is missing SMTP_FROM/SMTP_USER or SMTP_TO. Skipping.", file=sys.stderr)
        return 1

    if args.dry_run:
        REPORTS.mkdir(exist_ok=True)
        preview = REPORTS / "email-preview.eml"
        preview.write_bytes(message.as_bytes())
        print(f"Dry run: wrote {preview}")
        return 0

    if not setting(env, "SMTP_HOST"):
        print("SMTP_HOST is not set in .env. Skipping email.")
        return 0

    try:
        send_message(env, message)
    except Exception as error:
        print(f"Could not send email: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
