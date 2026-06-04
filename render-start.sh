#!/usr/bin/env bash
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_ai_training || true

exec gunicorn accountings.wsgi:application --bind "0.0.0.0:${PORT:-10000}"
