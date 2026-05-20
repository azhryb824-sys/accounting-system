from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [

    # ============================
    # Dashboard
    # ============================
    path('', views.home, name='home'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('reports/', views.reports_center, name='reports_center'),
    path('reports/sales.csv', views.export_sales_csv, name='export_sales_csv'),
    path('monthly-close/', views.monthly_close_list, name='monthly_close_list'),
    path('monthly-close/add/', views.monthly_close_add, name='monthly_close_add'),
    path('monthly-close/<int:close_id>/reopen/', views.monthly_close_reopen, name='monthly_close_reopen'),
    path('signup/', views.signup, name='signup'),

    # ============================
    # Accounts
    # ============================
    path('accounts/', views.accounts_list, name='accounts_list'),

    # ============================
    # Journal Entries (Double Entry)
    # ============================
    path('journal/', views.journal_list, name='journal_list'),
    path('journal/add/', views.journal_add, name='journal_add'),
    path('journal/<int:pk>/edit/', views.journal_edit, name='journal_edit'),
    path('journal/<int:pk>/copy/', views.journal_copy, name='journal_copy'),
    path('journal/<int:pk>/pdf/', views.journal_pdf, name='journal_pdf'),

    # ============================
    # Companies
    # ============================
    path('companies/', views.company_list, name='company_list'),
    path('companies/access/', views.company_access, name='company_access'),
    path('companies/add/', views.company_add, name='company_add'),
    path('companies/join/', views.company_join_request, name='company_join_request'),
    path('companies/join-requests/', views.company_join_requests, name='company_join_requests'),
    path('companies/join-requests/<int:request_id>/<str:decision>/', views.company_join_review, name='company_join_review'),

    # ============================
    # Branches
    # ============================
    path('branches/', views.branch_list, name='branch_list'),
    path('branches/add/', views.branch_add, name='branch_add'),
    path('branches/<int:id>/edit/', views.branch_edit, name='branch_edit'),
    path('branches/<int:id>/delete/', views.branch_delete, name='branch_delete'),

    # ============================
    # اختيار الشركة والفرع
    # ============================
    path('select/', views.select_company_branch, name='select_company_branch'),
    path('accounts/add/', views.account_add, name='account_add'),
]
