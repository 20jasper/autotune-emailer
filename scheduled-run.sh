#!/usr/bin/env bash
set -u

cd "$(dirname "$0")" || exit 1

./run.sh
status=$?

if command -v python3 >/dev/null 2>&1; then
  if [ "$status" -eq 0 ]; then
    python3 ./cgm_stats.py || true
  fi
  python3 ./send_report.py "$status" || true
else
  echo "python3 not found; skipping email (report is in reports/)." >&2
fi

exit "$status"
