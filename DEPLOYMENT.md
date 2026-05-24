# Deployment notes

Run these commands on the production server after pulling the latest code:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py update_ai_knowledge
```

Recommended environment variables:

```bash
DEBUG=False
SECRET_KEY=<long-random-secret-key>
DATABASE_URL=<postgres-url>
ALLOWED_HOSTS=accounting-system-t740.onrender.com
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
```

If the deployment platform already terminates HTTPS, keep `SECURE_PROXY_SSL_HEADER` enabled through the Django settings.
