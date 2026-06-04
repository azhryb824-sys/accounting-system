#!/usr/bin/env sh
set -eu

PORT="${PORT:-10000}"
echo "Starting accounting AI service on 0.0.0.0:${PORT}"
exec python -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
