#!/usr/bin/env python3

import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from html import escape
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
    return path.read_text(encoding="utf-8") if path.exists() else ""


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

    user = env.get("SMTP_USER", "")
    password = env.get("SMTP_PASS", "")
    to = env.get("SMTP_TO", "")
    sender = env.get("SMTP_FROM") or user

    if not user or not password or not to or not sender:
        print("Email is not configured.")
        return 0

    message = EmailMessage()
    message["Subject"] = "Nightscout Autotune failed" if failed else "Nightscout Autotune report"
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
        if html_report:
            report = html_report
            if stats:
                block = f"<h2>CGM stats</h2><pre>{escape(stats)}</pre>"
                report = (
                    report.replace("</body>", block + "</body>", 1)
                    if "</body>" in report
                    else report + block
                )
            message.add_alternative(report, subtype="html")
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
