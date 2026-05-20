from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from .forms import (
    AdminUserCreateForm,
    DisableUserForm,
    NationalIdLoginForm,
    RoleForm,
    SubscriptionPlanForm,
    SubscriptionRequestForm,
    UserEditForm,
    WarningForm,
)
from .models import Role, SubscriptionPlan, SubscriptionRequest, UserProfile, UserWarning

PRIMARY_ADMIN_NATIONAL_ID = "2572280689"


def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser
        or user.is_staff
        or getattr(getattr(user, "profile", None), "national_id", None) == PRIMARY_ADMIN_NATIONAL_ID
    )


def is_primary_admin(user):
    return user.is_authenticated and getattr(getattr(user, "profile", None), "national_id", None) == PRIMARY_ADMIN_NATIONAL_ID


def has_admin_permission(user, permission):
    return is_primary_admin(user) or user.is_superuser or (user.is_staff and user.has_perm(permission))


def admin_permission_required(permission):
    return user_passes_test(lambda user: has_admin_permission(user, permission))

def role_required(permission_codename):
    """
    تحقق مما إذا كان دور المستخدم يحتوي على صلاحية معينة (بناءً على الكود الخاص بها)
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            
            profile = getattr(request.user, 'profile', None)
            branch_company = None
            company_id = request.session.get("company_id")
            if company_id:
                from core.models import Company
                branch_company = Company.objects.filter(id=company_id).first()
            if profile and profile.role and branch_company and branch_company.has_active_subscription():
                role_has_permission = profile.role.permissions.filter(codename=permission_codename).exists()
                plan_has_permission = (
                    branch_company.active_plan
                    and branch_company.active_plan.permissions.filter(codename=permission_codename).exists()
                )
                if role_has_permission or plan_has_permission:
                    return view_func(request, *args, **kwargs)
            
            raise PermissionDenied
        return _wrapped_view
    return decorator

def login_view(request):
    if request.user.is_authenticated:
        return redirect("post_login")
    form = NationalIdLoginForm(request.POST or None)
    disabled_profile = None
    if request.method == "POST" and form.is_valid():
        national_id = form.cleaned_data["national_id"]
        password = form.cleaned_data["password"]
        profile = UserProfile.objects.select_related("user").filter(national_id=national_id).first()
        if not profile:
            messages.error(request, "رقم الهوية أو كلمة المرور غير صحيحة.")
        elif profile.is_disabled_by_admin:
            disabled_profile = profile
        else:
            user = authenticate(request, username=profile.user.username, password=password)
            if user:
                login(request, user)
                return redirect("post_login")
            messages.error(request, "رقم الهوية أو كلمة المرور غير صحيحة.")
    return render(request, "accounts/login.html", {"form": form, "disabled_profile": disabled_profile})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def post_login(request):
    profile = getattr(request.user, "profile", None)
    if profile and profile.is_disabled_by_admin:
        logout(request)
        return render(request, "accounts/account_disabled.html", {"profile": profile})
    if is_admin(request.user):
        return redirect("admin_selection")
    from core.models import CompanyMembership
    if not request.user.owned_companies.exists() and not CompanyMembership.objects.filter(user=request.user, is_active=True).exists():
        return redirect("company_access")
    return redirect("dashboard")


@user_passes_test(is_admin)
def admin_selection(request):
    return render(request, "accounts/admin_selection.html", {"title": "خيارات الدخول"})


@login_required
def subscription_plans(request):
    plans = SubscriptionPlan.objects.filter(is_active=True).select_related("role").order_by("display_order", "price", "name")
    requests = SubscriptionRequest.objects.filter(user=request.user).select_related("plan").order_by("-created_at")
    return render(request, "accounts/subscription_plans.html", {"plans": plans, "requests": requests})


@login_required
def subscription_request_create(request):
    form = SubscriptionRequestForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        subscription = form.save(commit=False)
        subscription.user = request.user
        subscription.save()
        messages.success(request, "تم إرسال طلب الاشتراك، وسيتم مراجعته من المشرف.")
        return redirect("subscription_plans")
    return render(request, "accounts/subscription_request_form.html", {"form": form})


@login_required
def privacy_notice(request):
    if request.method == "POST":
        profile = request.user.profile
        profile.privacy_acknowledged_at = timezone.now()
        profile.save(update_fields=["privacy_acknowledged_at"])
        messages.success(request, "تم حفظ موافقتك على إشعار الخصوصية.")
        return redirect("dashboard")
    return render(request, "accounts/privacy_notice.html")


@login_required
def fingerprint_settings(request):
    if request.method == "POST":
        profile = request.user.profile
        profile.fingerprint_enabled = True
        profile.save(update_fields=["fingerprint_enabled"])
        messages.success(request, "تم تفعيل خيار الدخول بالبصمة لهذا الحساب. الربط الكامل يتطلب جهازاً/متصفحاً يدعم WebAuthn.")
        return redirect("fingerprint_settings")
    return render(request, "accounts/fingerprint_settings.html")


@login_required(login_url='login')
@require_POST
def calendar_preference_update(request):
    calendar = request.POST.get("calendar")
    if calendar not in {"gregorian", "hijri"}:
        return JsonResponse({"ok": False, "error": "calendar"}, status=400)
    profile = getattr(request.user, "profile", None)
    if profile:
        profile.calendar_preference = calendar
        profile.save(update_fields=["calendar_preference"])
    request.session["calendar_preference"] = calendar
    return JsonResponse({"ok": True, "calendar": calendar})


@user_passes_test(is_admin)
def admin_dashboard(request):
    context = {
        "total_users": User.objects.count(),
        "pending_requests": SubscriptionRequest.objects.filter(status="pending").count(),
        "active_plans": SubscriptionPlan.objects.filter(is_active=True).count(),
        "latest_users": User.objects.order_by("-date_joined")[:5],
        "title": "لوحة تحكم الإدارة",
    }
    return render(request, "accounts/admin_dashboard.html", context)


@admin_permission_required("auth.view_user")
def admin_users(request):
    users = User.objects.select_related("profile", "profile__role").order_by("username")
    return render(request, "accounts/admin_users.html", {"users": users})


@admin_permission_required("auth.add_user")
def admin_user_create(request):
    can_manage_admins = is_primary_admin(request.user)
    form = AdminUserCreateForm(request.POST or None, can_manage_admins=can_manage_admins)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data["password"])
        if not can_manage_admins:
            user.is_staff = False
            user.is_superuser = False
        user.save()
        if can_manage_admins:
            form.save_m2m()
        UserProfile.objects.create(
            user=user,
            national_id=form.cleaned_data["national_id"],
            phone=form.cleaned_data.get("phone", ""),
            role=form.cleaned_data["role"],
        )
        messages.success(request, "تم إنشاء المستخدم.")
        return redirect("admin_users")
    return render(request, "accounts/admin_user_form.html", {"form": form, "can_manage_admins": can_manage_admins, "mode": "create"})


@admin_permission_required("auth.change_user")
def admin_user_edit(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target, defaults={"national_id": f"USR{target.id}"})
    can_manage_admins = is_primary_admin(request.user)
    form = UserEditForm(request.POST or None, instance=target, profile=profile, can_manage_admins=can_manage_admins)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        if not can_manage_admins:
            user.is_staff = target.is_staff
            user.is_superuser = target.is_superuser
        user.save()
        if can_manage_admins:
            form.save_m2m()
        profile.national_id = form.cleaned_data["national_id"]
        profile.phone = form.cleaned_data.get("phone", "")
        profile.role = form.cleaned_data.get("role")
        profile.save(update_fields=["national_id", "phone", "role"])
        messages.success(request, "تم تحديث بيانات المستخدم والصلاحيات.")
        return redirect("admin_users")
    return render(request, "accounts/admin_user_form.html", {"form": form, "target": target, "can_manage_admins": can_manage_admins, "mode": "edit"})


@admin_permission_required("auth.change_user")
def admin_user_disable(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target, defaults={"national_id": f"USR{target.id}"})
    form = DisableUserForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم تحديث حالة الحساب.")
        return redirect("admin_users")
    return render(request, "accounts/admin_disable_user.html", {"form": form, "target": target})


@admin_permission_required("auth.change_user")
def admin_user_exempt(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target, defaults={"national_id": f"USR{target.id}"})
    profile.is_subscription_exempt = not profile.is_subscription_exempt
    profile.save(update_fields=["is_subscription_exempt"])
    messages.success(request, "تم تحديث حالة الإعفاء.")
    return redirect("admin_users")


@user_passes_test(is_primary_admin)
@require_POST
def admin_user_remove_admin(request, user_id):
    target = get_object_or_404(User, id=user_id)
    target_profile = getattr(target, "profile", None)
    if target_profile and target_profile.national_id == PRIMARY_ADMIN_NATIONAL_ID:
        messages.error(request, "لا يمكن إزالة إشراف المشرف الرئيسي.")
        return redirect("admin_users")
    target.is_staff = False
    target.is_superuser = False
    target.user_permissions.clear()
    target.save(update_fields=["is_staff", "is_superuser"])
    messages.success(request, "تمت إزالة صلاحية الإشراف مع إبقاء الدور العادي للمستخدم.")
    return redirect("admin_users")


@admin_permission_required("accounts.add_userwarning")
def admin_warning_create(request, user_id):
    target = get_object_or_404(User, id=user_id)
    form = WarningForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        warning = form.save(commit=False)
        warning.user = target
        warning.created_by = request.user
        warning.save()
        messages.success(request, "تم إرسال الإنذار.")
        return redirect("admin_users")
    return render(request, "accounts/admin_warning_form.html", {"form": form, "target": target})


@admin_permission_required("accounts.view_role")
def admin_roles(request):
    roles = Role.objects.all()
    return render(request, "accounts/admin_roles.html", {"roles": roles})


@admin_permission_required("accounts.change_role")
def admin_role_form(request, role_id=None):
    role = get_object_or_404(Role, id=role_id) if role_id else None
    title = "تعديل دور" if role_id else "إضافة دور جديد"
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ الدور.")
        return redirect("admin_roles")
    return render(request, "accounts/admin_role_form.html", {"form": form, "title": title})


@admin_permission_required("accounts.view_subscriptionplan")
def admin_plans(request):
    plans = SubscriptionPlan.objects.select_related("role").all()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all")
    role_id = request.GET.get("role", "")

    if query:
        plans = plans.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(features__icontains=query)
            | Q(role__name__icontains=query)
        )
    if status == "active":
        plans = plans.filter(is_active=True)
    elif status == "inactive":
        plans = plans.filter(is_active=False)
    if role_id:
        plans = plans.filter(role_id=role_id)

    plans = plans.order_by("display_order", "price", "name")
    return render(request, "accounts/admin_plans.html", {
        "plans": plans,
        "roles": Role.objects.order_by("name"),
        "query": query,
        "status": status,
        "selected_role": role_id,
        "active_count": SubscriptionPlan.objects.filter(is_active=True).count(),
        "inactive_count": SubscriptionPlan.objects.filter(is_active=False).count(),
    })


@admin_permission_required("accounts.change_subscriptionplan")
def admin_plan_form(request, plan_id=None):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id) if plan_id else None
    form = SubscriptionPlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ الباقة.")
        return redirect("admin_plans")
    return render(request, "accounts/admin_plan_form.html", {"form": form})


@admin_permission_required("accounts.change_subscriptionplan")
@require_POST
def admin_plan_toggle(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    plan.is_active = not plan.is_active
    plan.save(update_fields=["is_active"])
    messages.success(request, "تم تحديث حالة الباقة.")
    return redirect("admin_plans")


@admin_permission_required("accounts.add_subscriptionplan")
@require_POST
def admin_plan_duplicate(request, plan_id):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id)
    permissions = list(plan.permissions.all())
    plan.pk = None
    plan.name = f"{plan.name} - نسخة"
    plan.is_active = False
    plan.display_order += 1
    plan.save()
    plan.permissions.set(permissions)
    messages.success(request, "تم نسخ الباقة. يمكنك تعديل النسخة قبل تفعيلها.")
    return redirect("admin_plan_edit", plan.id)


@admin_permission_required("accounts.view_subscriptionrequest")
def admin_subscription_requests(request):
    requests = SubscriptionRequest.objects.select_related("user", "plan").order_by("-created_at")
    return render(request, "accounts/admin_subscription_requests.html", {"requests": requests})


@admin_permission_required("accounts.change_subscriptionrequest")
def admin_subscription_review(request, request_id, decision):
    subscription = get_object_or_404(SubscriptionRequest, id=request_id)
    subscription.reviewed_at = timezone.now()
    if decision == "approve":
        subscription.status = "approved"
        subscription.starts_at = timezone.now()
        subscription.ends_at = timezone.now() + timedelta(days=subscription.plan.duration_days)
        profile = subscription.user.profile
        profile.role = subscription.requested_role or subscription.plan.role
        profile.save(update_fields=["role"])
        subscription.user.user_permissions.add(*subscription.plan.permissions.all())
        if subscription.company:
            subscription.company.subscription_status = "active"
            subscription.company.active_plan = subscription.plan
            subscription.company.subscription_starts_at = subscription.starts_at
            subscription.company.subscription_ends_at = subscription.ends_at
            subscription.company.trial_ends_at = (
                subscription.starts_at + timedelta(days=subscription.plan.trial_days)
                if subscription.plan.trial_days
                else None
            )
            if subscription.requested_role:
                subscription.company.owner_role = subscription.requested_role
            subscription.company.save(update_fields=[
                "subscription_status",
                "active_plan",
                "subscription_starts_at",
                "subscription_ends_at",
                "trial_ends_at",
                "owner_role",
            ])
        messages.success(request, "تم قبول الاشتراك وتفعيل الدور.")
    else:
        subscription.status = "rejected"
        if subscription.company:
            subscription.company.subscription_status = "rejected"
            subscription.company.active_plan = None
            subscription.company.subscription_starts_at = None
            subscription.company.subscription_ends_at = None
            subscription.company.trial_ends_at = None
            subscription.company.save(update_fields=[
                "subscription_status",
                "active_plan",
                "subscription_starts_at",
                "subscription_ends_at",
                "trial_ends_at",
            ])
        messages.success(request, "تم رفض طلب الاشتراك.")
    subscription.save()
    return redirect("admin_subscription_requests")
