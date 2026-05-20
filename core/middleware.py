from django.contrib.sessions.exceptions import SessionInterrupted
from django.shortcuts import redirect

from .subscription import CompanySubscriptionRequiredMiddleware


class GracefulSessionInterruptedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except SessionInterrupted:
            return redirect("login")
