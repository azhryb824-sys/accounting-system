from django.contrib import admin

from .models import FingerprintCredential, Role, SubscriptionPlan, SubscriptionRequest, UserProfile, UserWarning


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "requires_subscription")
    filter_horizontal = ("permissions",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "national_id", "role", "is_subscription_exempt", "is_disabled_by_admin", "fingerprint_enabled")
    search_fields = ("user__username", "national_id", "user__first_name", "user__last_name")
    list_filter = ("role", "is_subscription_exempt", "is_disabled_by_admin")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "price", "duration_days", "is_active")
    list_filter = ("role", "is_active")


@admin.register(SubscriptionRequest)
class SubscriptionRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "created_at", "reviewed_at")
    list_filter = ("status", "plan")


admin.site.register(UserWarning)
admin.site.register(FingerprintCredential)
