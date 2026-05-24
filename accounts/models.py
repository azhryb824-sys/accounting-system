from django.conf import settings
from django.contrib.auth.models import Permission
from django.db import models


class Role(models.Model):
    BRANCH_ACCESS_CHOICES = [
        ("all", "كل فروع الشركة"),
        ("single", "فرع واحد فقط"),
    ]

    name = models.CharField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    permissions = models.ManyToManyField(Permission, blank=True)
    requires_subscription = models.BooleanField(default=False)
    branch_access = models.CharField(max_length=10, choices=BRANCH_ACCESS_CHOICES, default="all")

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    CALENDAR_CHOICES = [
        ("gregorian", "ميلادي"),
        ("hijri", "هجري"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    national_id = models.CharField(max_length=20, unique=True, verbose_name="رقم الهوية")
    phone = models.CharField(max_length=30, blank=True, verbose_name="رقم الجوال")
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL, verbose_name="الدور")
    is_subscription_exempt = models.BooleanField(default=False)
    is_disabled_by_admin = models.BooleanField(default=False)
    disabled_reason = models.TextField(blank=True)
    privacy_acknowledged_at = models.DateTimeField(null=True, blank=True)
    fingerprint_enabled = models.BooleanField(default=False)
    calendar_preference = models.CharField(max_length=20, choices=CALENDAR_CHOICES, default="gregorian")

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} - {self.national_id}"


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=120)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="plans")
    permissions = models.ManyToManyField(Permission, blank=True, related_name="subscription_plans")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    yearly_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    duration_days = models.PositiveIntegerField(default=30)
    trial_days = models.PositiveIntegerField(default=7)
    max_companies = models.PositiveIntegerField(default=1)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    features = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} - {self.price}"


class SubscriptionRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "بانتظار الموافقة"),
        ("approved", "مقبول"),
        ("rejected", "مرفوض"),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription_requests")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    company = models.ForeignKey("core.Company", on_delete=models.CASCADE, null=True, blank=True, related_name="subscription_requests")
    requested_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name="subscription_requests")
    bank_name = models.CharField(max_length=120)
    transfer_reference = models.CharField(max_length=120, blank=True)
    transfer_notice = models.FileField(upload_to="subscription_notices/", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    admin_note = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan.name} - {self.get_status_display()}"


class UserWarning(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_warnings")
    title = models.CharField(max_length=160)
    message = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="warnings_created")
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class FingerprintCredential(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="fingerprint_credentials")
    credential_id = models.CharField(max_length=255, unique=True)
    public_key = models.TextField(blank=True)
    device_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.device_name or self.credential_id[:12]}"
