#!/usr/bin/env sh
set -eu

PORT="${PORT:-10000}"
exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
