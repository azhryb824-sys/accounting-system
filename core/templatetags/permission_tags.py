from django import template

register = template.Library()


@register.simple_tag
def can_access(request, permission_codename):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True

    profile = getattr(user, "profile", None)
    company_id = request.session.get("company_id")
    company = None
    if company_id:
        from core.models import Company
        company = Company.objects.filter(id=company_id).select_related("active_plan").first()

    from accounts.views import user_has_business_permission
    if user_has_business_permission(user, permission_codename, company):
        return True
    if not profile or not company:
        return False
    if not company.has_active_subscription():
        return False

    role_has_permission = (
        profile.role
        and profile.role.permissions.filter(codename=permission_codename).exists()
    )
    plan_has_permission = (
        company.active_plan
        and company.active_plan.permissions.filter(codename=permission_codename).exists()
    )
    return bool(role_has_permission or plan_has_permission)
