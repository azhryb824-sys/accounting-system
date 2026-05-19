from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("post-login/", views.post_login, name="post_login"),
    path("privacy/", views.privacy_notice, name="privacy_notice"),
    path("fingerprint/", views.fingerprint_settings, name="fingerprint_settings"),
    path("subscriptions/", views.subscription_plans, name="subscription_plans"),
    path("subscriptions/request/", views.subscription_request_create, name="subscription_request_create"),
    path("admin/dashboard/", views.admin_dashboard, name="admin_home"),
    path("admin/selection/", views.admin_selection, name="admin_selection"),
    path("admin/users/", views.admin_users, name="admin_users"),
    path("admin/users/add/", views.admin_user_create, name="admin_user_create"),
    path("admin/users/<int:user_id>/disable/", views.admin_user_disable, name="admin_user_disable"),
    path("admin/users/<int:user_id>/exempt/", views.admin_user_exempt, name="admin_user_exempt"),
    path("admin/users/<int:user_id>/warning/", views.admin_warning_create, name="admin_warning_create"),
    path("admin/roles/", views.admin_roles, name="admin_roles"),
    path("admin/roles/add/", views.admin_role_form, name="admin_role_add"),
    path("admin/roles/<int:role_id>/edit/", views.admin_role_form, name="admin_role_edit"),
    path("admin/plans/", views.admin_plans, name="admin_plans"),
    path("admin/plans/add/", views.admin_plan_form, name="admin_plan_add"),
    path("admin/plans/<int:plan_id>/edit/", views.admin_plan_form, name="admin_plan_edit"),
    path("admin/subscription-requests/", views.admin_subscription_requests, name="admin_subscription_requests"),
    path("admin/subscription-requests/<int:request_id>/<str:decision>/", views.admin_subscription_review, name="admin_subscription_review"),
]
