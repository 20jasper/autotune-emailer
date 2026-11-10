#!/usr/bin/env bash
#
# Run Autotune, then email the report (or the failure log).
# This is what the systemd timer / cron entry calls.
#
set -u

cd "$(dirname "$0")"

./run.sh
status=$?

if command -v python3 >/dev/null 2>&1; then
  python3 ./send_report.py --status "$status" || true
else
  echo "python3 not found; skipping email (report is in reports/)." >&2
fi

exit "$status"
