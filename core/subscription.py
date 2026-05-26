from django.contrib import messages
from django.shortcuts import redirect
from django.urls import resolve, Resolver404

from .models import Company


SUBSCRIPTION_EXEMPT_URL_NAMES = {
    "home",
    "login",
    "logout",
    "signup",
    "post_login",
    "privacy_notice",
    "fingerprint_settings",
    "subscription_plans",
    "subscription_request_create",
    "company_add",
    "company_list",
    "company_access",
    "company_join_request",
    "company_join_requests",
    "company_join_review",
    "select_company_branch",
    "admin_selection",
    "admin_home",
    "admin_users",
    "admin_user_create",
    "admin_user_edit",
    "admin_user_disable",
    "admin_user_exempt",
    "admin_user_remove_admin",
    "admin_warning_create",
    "admin_roles",
    "admin_role_add",
    "admin_role_edit",
    "admin_plans",
    "admin_plan_add",
    "admin_plan_edit",
    "admin_plan_toggle",
    "admin_plan_duplicate",
    "admin_subscription_requests",
    "admin_subscription_review",
}


class CompanySubscriptionRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = getattr(request, "resolver_match", None)
        url_name = getattr(match, "url_name", None)
        if url_name is None:
            try:
                url_name = resolve(request.path_info).url_name
            except Resolver404:
                url_name = None
        if (
            hasattr(request, "user")
            and request.user.is_authenticated
            and not _is_system_admin(request.user)
            and url_name not in SUBSCRIPTION_EXEMPT_URL_NAMES
        ):
            from .access import user_can_access_branch
            from .models import Branch, CompanyMembership

            user_company_ids = set(CompanyMembership.objects.filter(user=request.user, is_active=True).values_list("company_id", flat=True))
            owned_company_ids = set(request.user.owned_companies.values_list("id", flat=True))
            allowed_company_ids = user_company_ids | owned_company_ids
            if not allowed_company_ids:
                return redirect("company_access")
            company_id = request.session.get("company_id")
            try:
                selected_company_id = int(company_id) if company_id else None
            except (TypeError, ValueError):
                selected_company_id = None
            if selected_company_id and selected_company_id not in allowed_company_ids:
                request.session.pop("company_id", None)
                request.session.pop("company_name", None)
                request.session.pop("branch_id", None)
                request.session.pop("branch_name", None)
                messages.warning(request, "لا يمكنك استخدام شركة غير مرتبطة بحسابك.")
                return redirect("company_access")
            if company_id:
                company = Company.objects.filter(id=company_id).first()
                if company and not company.has_active_subscription():
                    messages.warning(request, "لا يمكن استخدام ميزات الشركة قبل وجود اشتراك سارٍ.")
                    return redirect("company_add")
            branch_id = request.session.get("branch_id")
            branch = Branch.objects.filter(id=branch_id, company_id=company_id).select_related("company").first() if branch_id and company_id else None
            if not branch or not user_can_access_branch(request.user, branch):
                request.session.pop("branch_id", None)
                request.session.pop("branch_name", None)
                messages.warning(request, "اختر فرعا مصرحا لحسابك قبل متابعة العمل.")
                return redirect("select_company_branch")
        return self.get_response(request)


def _is_system_admin(user):
    if user.is_superuser:
        return True
    from accounts.views import is_primary_admin

    return is_primary_admin(user)
