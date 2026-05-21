@echo off
setlocal
cd /d "%~dp0"

if not exist starter.sqlite3 (
    echo Creating starter database...
    set SQLITE_NAME=starter.sqlite3
    python manage.py migrate
    python manage.py bootstrap_admin --username admin --password "Admin@12345" --email "admin@example.com" --national-id 2572280689
) else (
    echo starter.sqlite3 already exists.
)

set SQLITE_NAME=starter.sqlite3
echo.
echo Admin national id: 2572280689
echo Admin password: Admin@12345
echo.
python manage.py runserver
