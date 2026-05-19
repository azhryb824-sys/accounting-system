from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from .forms import (
    DisableUserForm,
    NationalIdLoginForm,
    RoleForm,
    SubscriptionPlanForm,
    SubscriptionRequestForm,
    UserCreateForm,
    WarningForm,
)
from .models import Role, SubscriptionPlan, SubscriptionRequest, UserProfile, UserWarning


def is_admin(user):
    return user.is_authenticated and user.is_superuser

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
            if profile and profile.role:
                if profile.role.permissions.filter(codename=permission_codename).exists():
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
    if request.user.is_superuser:
        return redirect("admin_selection")
    return redirect("dashboard")


@user_passes_test(is_admin)
def admin_selection(request):
    return render(request, "accounts/admin_selection.html", {"title": "خيارات الدخول"})


@login_required
def subscription_plans(request):
    plans = SubscriptionPlan.objects.filter(is_active=True).select_related("role")
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


@user_passes_test(is_admin)
def admin_users(request):
    users = User.objects.select_related("profile", "profile__role").order_by("username")
    return render(request, "accounts/admin_users.html", {"users": users})


@user_passes_test(is_admin)
def admin_user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.set_password(form.cleaned_data["password"])
        user.save()
        UserProfile.objects.create(
            user=user,
            national_id=form.cleaned_data["national_id"],
            role=form.cleaned_data["role"],
        )
        messages.success(request, "تم إنشاء المستخدم.")
        return redirect("admin_users")
    return render(request, "accounts/admin_user_form.html", {"form": form})


@user_passes_test(is_admin)
def admin_user_disable(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target, defaults={"national_id": f"USR{target.id}"})
    form = DisableUserForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم تحديث حالة الحساب.")
        return redirect("admin_users")
    return render(request, "accounts/admin_disable_user.html", {"form": form, "target": target})


@user_passes_test(is_admin)
def admin_user_exempt(request, user_id):
    target = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target, defaults={"national_id": f"USR{target.id}"})
    profile.is_subscription_exempt = not profile.is_subscription_exempt
    profile.save(update_fields=["is_subscription_exempt"])
    messages.success(request, "تم تحديث حالة الإعفاء.")
    return redirect("admin_users")


@user_passes_test(is_admin)
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


@user_passes_test(is_admin)
def admin_roles(request):
    roles = Role.objects.all()
    return render(request, "accounts/admin_roles.html", {"roles": roles})


@user_passes_test(is_admin)
def admin_role_form(request, role_id=None):
    role = get_object_or_404(Role, id=role_id) if role_id else None
    title = "تعديل دور" if role_id else "إضافة دور جديد"
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ الدور.")
        return redirect("admin_roles")
    return render(request, "accounts/admin_role_form.html", {"form": form, "title": title})


@user_passes_test(is_admin)
def admin_plans(request):
    plans = SubscriptionPlan.objects.select_related("role").all()
    return render(request, "accounts/admin_plans.html", {"plans": plans})


@user_passes_test(is_admin)
def admin_plan_form(request, plan_id=None):
    plan = get_object_or_404(SubscriptionPlan, id=plan_id) if plan_id else None
    form = SubscriptionPlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم حفظ الباقة.")
        return redirect("admin_plans")
    return render(request, "accounts/admin_plan_form.html", {"form": form})


@user_passes_test(is_admin)
def admin_subscription_requests(request):
    requests = SubscriptionRequest.objects.select_related("user", "plan").order_by("-created_at")
    return render(request, "accounts/admin_subscription_requests.html", {"requests": requests})


@user_passes_test(is_admin)
def admin_subscription_review(request, request_id, decision):
    subscription = get_object_or_404(SubscriptionRequest, id=request_id)
    subscription.reviewed_at = timezone.now()
    if decision == "approve":
        subscription.status = "approved"
        subscription.starts_at = timezone.now()
        subscription.ends_at = timezone.now() + timedelta(days=subscription.plan.duration_days)
        profile = subscription.user.profile
        profile.role = subscription.plan.role
        profile.save(update_fields=["role"])
        messages.success(request, "تم قبول الاشتراك وتفعيل الدور.")
    else:
        subscription.status = "rejected"
        messages.success(request, "تم رفض طلب الاشتراك.")
    subscription.save()
    return redirect("admin_subscription_requests")
