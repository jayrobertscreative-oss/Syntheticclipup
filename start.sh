#!/bin/sh
# Runs one processing worker and the web server in the same container,
# so both share the same disk (uploads, clips, database).
set -e
python -m app.worker &
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
