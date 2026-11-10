#!/usr/bin/env python3

from __future__ import annotations

import re
import smtplib
import ssl
import sys
from contextlib import suppress
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"


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
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def send(env: dict[str, str], message: EmailMessage) -> None:
    host = env.get("SMTP_HOST", "")
    port = int(env.get("SMTP_PORT", "587"))
    user = env.get("SMTP_USER", "")
    password = re.sub(r"\s+", "", env.get("SMTP_PASS", ""))
    use_ssl = truthy(env.get("SMTP_SSL", "false"))
    use_starttls = truthy(env.get("SMTP_STARTTLS", "true")) and not use_ssl
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


def main() -> int:
    status = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    env = load_env(ROOT / ".env")
    text = read(REPORTS / "autotune_recommendations.log")
    html = read(REPORTS / "autotune_recommendations.html")
    profile = read(REPORTS / "tuned-profile.json")
    log = read(REPORTS / "last-run.log")
    failed = status != 0 or not text

    if not env.get("SMTP_HOST") or not env.get("SMTP_TO") or not env.get("SMTP_FROM"):
        print("Email is not configured.")
        return 0

    message = EmailMessage()
    message["Subject"] = "Nightscout Autotune failed" if failed else "Nightscout Autotune report"
    message["From"] = env["SMTP_FROM"]
    message["To"] = env["SMTP_TO"]

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
        message.set_content(text)
        if html:
            message.add_attachment(
                html.encode("utf-8"),
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

    try:
        send(env, message)
    except Exception as error:
        print(f"Email failed: {error}")
        return 1
    print("Email sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
