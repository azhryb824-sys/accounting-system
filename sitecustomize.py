try:
    from django.conf import settings
    from django.contrib.sessions.exceptions import SessionInterrupted
    from django.contrib.sessions.middleware import SessionMiddleware
    from django.shortcuts import redirect

    _original_process_response = SessionMiddleware.process_response

    def _process_response_without_session_crash(self, request, response):
        try:
            return _original_process_response(self, request, response)
        except SessionInterrupted:
            return redirect("login")

    SessionMiddleware.process_response = _process_response_without_session_crash
    subscription_middleware = "core.subscription.CompanySubscriptionRequiredMiddleware"
    if subscription_middleware not in settings.MIDDLEWARE:
        settings.MIDDLEWARE.append(subscription_middleware)
except Exception:
    pass
