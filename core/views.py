import csv
import json
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login
from .models import Account, JournalEntry, Company, Branch, CompanyJoinRequest, CompanyMembership, Employee, EmployeeAdvance, JournalEntryLine, MonthlyClose, SalaryRecord
from .forms import CompanyForm, CompanyJoinRequestForm, CompanySubscriptionRequestForm, BranchForm, JournalEntryForm, JournalEntryLineFormSet, AccountForm, MonthlyCloseForm, EmployeeForm, SalaryRecordForm, EmployeeAdvanceForm
from .services.accounting import create_balanced_entry
from .services.monthly_close import assert_month_open
from .services.payroll import approve_salary, pay_salary
from .access import user_accessible_branches, user_can_access_branch
from accounts.forms import UserRegistrationForm
from accounts.models import Role, SubscriptionRequest, UserProfile
from accounts.views import is_primary_admin, role_required, user_has_business_permission

APP_VERSION = "2026-06-04-dashboard-500-fix"


def health_version(request):
    return JsonResponse({
        "version": APP_VERSION,
        "company_add_plan_fix": True,
        "dashboard_account_count_fix": True,
        "ai_training_entries": 39,
    })


# ============================
#  Home Page (Landing)
# ============================
def home(request):
    """ط§ظ„طµظپط­ط© ط§ظ„ط±ط¦ظٹط³ظٹط© ط§ظ„طھظٹ طھط¸ظ‡ط± ظ‚ط¨ظ„ طھط³ط¬ظٹظ„ ط§ظ„ط¯ط®ظˆظ„"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html', {
        "title": "ظ…ط±ط­ط¨ط§ظ‹ ط¨ظƒ ظپظٹ ظ†ط¸ط§ظ… ط§ظ„ظ…ط­ط§ط³ط¨ط© ط§ظ„ط°ظƒظٹ",
    })


# ============================
#  Dashboard
# ============================
@login_required(login_url='login')
def dashboard(request):
    branch_id = request.session.get('branch_id')

    # ط¥ط°ط§ ظ„ظ… ظٹطھظ… ط§ط®طھظٹط§ط± ظپط±ط¹طŒ ظˆط¬ظ‡ ط§ظ„ظ…ط³طھط®ط¯ظ… ظ„طµظپط­ط© ط§ظ„ط§ط®طھظٹط§ط±
    if not branch_id: # _("If no branch is selected, redirect the user to the selection page")
        if _can_use_system_without_company_scope(request.user):
            return render(request, 'core/dashboard.html', _admin_dashboard_context(request))
        if not _user_companies(request.user).exists():
            return redirect('company_access')
        return redirect('select_company_branch')

    company = Company.objects.filter(id=request.session.get('company_id')).first()
    can_view_account = user_has_business_permission(request.user, 'view_account', company)
    can_view_journal = user_has_business_permission(request.user, 'view_journalentry', company)
    context = {
        "accounts_count": Account.objects.count() if can_view_account else 0,
        "entries_count": JournalEntry.objects.filter(branch_id=branch_id).count() if can_view_journal else 0,
        "branch_name": request.session.get("branch_name"),
        "company_name": request.session.get("company_name"),
        "title": "ظ„ظˆط­ط© ط§ظ„طھط­ظƒظ…",
    }
    from invoicing.models import Invoice, Item, PurchaseInvoice

    invoices = Invoice.objects.filter(branch_id=branch_id)
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id)
    items = Item.objects.filter(branch_id=branch_id)
    salaries = SalaryRecord.objects.filter(branch_id=branch_id)
    advances = EmployeeAdvance.objects.filter(branch_id=branch_id, status='open')
    today = timezone.localdate()
    can_view_invoice = user_has_business_permission(request.user, 'view_invoice', company)
    can_view_purchase = user_has_business_permission(request.user, 'view_purchaseinvoice', company)
    can_view_item = user_has_business_permission(request.user, 'view_item', company)
    can_view_salary = user_has_business_permission(request.user, 'view_salaryrecord', company)
    can_view_advance = user_has_business_permission(request.user, 'view_employeeadvance', company)
    salary_total = salaries.aggregate(total=Coalesce(Sum('net_salary'), Decimal('0')))['total'] if can_view_salary else Decimal('0')
    advances_total = advances.aggregate(total=Coalesce(Sum(F('amount') - F('paid_amount')), Decimal('0')))['total'] if can_view_advance else Decimal('0')
    sales_total = invoices.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'] if can_view_invoice else Decimal('0')
    purchases_total = purchases.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'] if can_view_purchase else Decimal('0')
    context.update({
        "invoices_count": invoices.count() if can_view_invoice else 0,
        "today_invoices_count": invoices.filter(issue_date__date=today).count() if can_view_invoice else 0,
        "sales_total": sales_total,
        "purchases_total": purchases_total,
        "salary_total": salary_total,
        "employee_advances_total": advances_total,
        "operating_result": sales_total - purchases_total - salary_total,
        "inventory_value": items.aggregate(total=Coalesce(Sum(F('quantity') * F('cost')), Decimal('0')))['total'] if can_view_item else Decimal('0'),
        "low_stock_count": items.filter(quantity__lte=F('min_quantity'), is_active=True).count() if can_view_item else 0,
        "low_stock_items": items.filter(quantity__lte=F('min_quantity'), is_active=True).order_by('quantity')[:6] if can_view_item else [],
    })
    return render(request, 'core/dashboard.html', context)


def _can_use_system_without_company_scope(user):
    return user.is_authenticated and (is_primary_admin(user) or user.is_superuser)


def _admin_dashboard_context(request):
    return {
        "accounts_count": 0,
        "entries_count": 0,
        "branch_name": "بدون فرع محدد",
        "company_name": "بدون شركة محددة",
        "title": "لوحة تحكم المشرف",
        "invoices_count": 0,
        "today_invoices_count": 0,
        "sales_total": Decimal('0'),
        "purchases_total": Decimal('0'),
        "salary_total": Decimal('0'),
        "employee_advances_total": Decimal('0'),
        "operating_result": Decimal('0'),
        "inventory_value": Decimal('0'),
        "low_stock_count": 0,
        "low_stock_items": [],
        "admin_mode_without_scope": True,
        "companies_count": Company.objects.count(),
        "branches_count": Branch.objects.count(),
        "users_count": UserProfile.objects.count(),
    }


def _user_companies(user):
    if user.is_superuser:
        return Company.objects.all()
    member_company_ids = CompanyMembership.objects.filter(user=user, is_active=True).values_list('company_id', flat=True)
    return Company.objects.filter(Q(owner=user) | Q(id__in=member_company_ids)).distinct()


def _user_branches(user):
    return user_accessible_branches(user)


def _can_view_company_branches(user, company):
    if user.is_superuser or company.owner_id == user.id:
        return True
    return _user_branches(user).filter(company=company).exists()


def _can_add_branch_to_company(user, company):
    if user.is_superuser or company.owner_id == user.id:
        return True
    return user_has_business_permission(user, 'add_branch', company)

# ============================
#  Reports Center
# ============================
def _date_range_from_request(request):
    today = timezone.localdate()
    date_from = request.GET.get('from') or today.replace(day=1).isoformat()
    date_to = request.GET.get('to') or today.isoformat()
    return date_from, date_to


@login_required(login_url='login')
@role_required('view_journalentry')
def reports_center(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return redirect('select_company_branch')

    from invoicing.models import Invoice, InvoiceItem, Item, PurchaseInvoice

    date_from, date_to = _date_range_from_request(request)
    invoices = Invoice.objects.filter(branch_id=branch_id, issue_date__date__range=[date_from, date_to])
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id, issue_date__range=[date_from, date_to])
    items = Item.objects.filter(branch_id=branch_id)
    totals = invoices.aggregate(
        sales=Coalesce(Sum('total_amount'), Decimal('0')),
        vat=Coalesce(Sum('total_vat'), Decimal('0')),
        sales_with_vat=Coalesce(Sum('total_with_vat'), Decimal('0')),
    )
    purchases_total = purchases.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total']

    return render(request, 'core/reports_center.html', {
        "title": "ظ…ط±ظƒط² ط§ظ„طھظ‚ط§ط±ظٹط±",
        "date_from": date_from,
        "date_to": date_to,
        "sales_total": totals['sales'],
        "vat_total": totals['vat'],
        "sales_with_vat": totals['sales_with_vat'],
        "purchases_total": purchases_total,
        "net_flow": totals['sales_with_vat'] - purchases_total,
        "invoice_count": invoices.count(),
        "purchase_count": purchases.count(),
        "top_customers": invoices.values('customer__name').annotate(
            total=Coalesce(Sum('total_with_vat'), Decimal('0')),
            invoices=Count('id'),
        ).order_by('-total')[:5],
        "top_items": InvoiceItem.objects.filter(
            branch_id=branch_id,
            invoice__issue_date__date__range=[date_from, date_to],
        ).values('item__name').annotate(
            quantity=Coalesce(Sum('quantity'), Decimal('0')),
            total=Coalesce(Sum('line_total_with_vat'), Decimal('0')),
        ).order_by('-total')[:5],
        "low_stock_items": items.filter(quantity__lte=F('min_quantity'), is_active=True).order_by('quantity', 'name'),
        "inventory_value": items.aggregate(total=Coalesce(Sum(F('quantity') * F('cost')), Decimal('0')))['total'],
    })


@login_required(login_url='login')
@role_required('view_salaryrecord')
def payroll_report(request):
    companies = _user_companies(request.user)
    selected_company_id = request.GET.get("company") or request.session.get("company_id")
    year = int(request.GET.get("year") or timezone.localdate().year)
    month = int(request.GET.get("month") or timezone.localdate().month)
    salaries = SalaryRecord.objects.filter(branch__in=_user_branches(request.user), year=year, month=month).select_related("employee", "company", "branch", "accrual_entry", "payment_entry")
    if selected_company_id:
        salaries = salaries.filter(company_id=selected_company_id)
    totals = salaries.aggregate(
        basic=Coalesce(Sum('basic_salary'), Decimal('0')),
        allowances=Coalesce(Sum('allowances'), Decimal('0')),
        deductions=Coalesce(Sum('deductions'), Decimal('0')),
        advances=Coalesce(Sum('advances_deduction'), Decimal('0')),
        net=Coalesce(Sum('net_salary'), Decimal('0')),
    )
    totals["gross"] = totals["basic"] + totals["allowances"] - totals["deductions"]
    return render(request, 'core/payroll_report.html', {
        "title": "ظƒط´ظپ ط§ظ„ط±ظˆط§طھط¨ ط§ظ„ط´ظ‡ط±ظٹ",
        "companies": companies.order_by("name"),
        "selected_company_id": str(selected_company_id or ""),
        "year": year,
        "month": month,
        "salaries": salaries.order_by("employee__name"),
        "totals": totals,
    })


@login_required(login_url='login')
@role_required('view_employeeadvance')
def advance_report(request):
    companies = _user_companies(request.user)
    advances = EmployeeAdvance.objects.filter(branch__in=_user_branches(request.user)).select_related("employee", "company", "branch", "journal_entry")
    status = request.GET.get("status") or ""
    if status:
        advances = advances.filter(status=status)
    totals = advances.aggregate(
        amount=Coalesce(Sum('amount'), Decimal('0')),
        paid=Coalesce(Sum('paid_amount'), Decimal('0')),
    )
    totals["remaining"] = totals["amount"] - totals["paid"]
    return render(request, 'core/advance_report.html', {
        "title": "ظƒط´ظپ ط³ظ„ظپ ط§ظ„ظ…ظˆط¸ظپظٹظ†",
        "status": status,
        "advances": advances.order_by("employee__name", "-date"),
        "totals": totals,
    })


@login_required(login_url='login')
@role_required('view_journalentry')
def unposted_operations_report(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return redirect('select_company_branch')
    from invoicing.models import Invoice, PurchaseInvoice

    return render(request, 'core/unposted_operations_report.html', {
        "title": "ط¹ظ…ظ„ظٹط§طھ ط؛ظٹط± ظ…ط±ط­ظ„ط©",
        "draft_salaries": SalaryRecord.objects.filter(branch_id=branch_id, accrual_entry__isnull=True).select_related("employee"),
        "unpaid_salaries": SalaryRecord.objects.filter(branch_id=branch_id, status='approved', payment_entry__isnull=True).select_related("employee"),
        "unposted_advances": EmployeeAdvance.objects.filter(branch_id=branch_id, journal_entry__isnull=True).select_related("employee"),
        "unposted_invoices": Invoice.objects.filter(branch_id=branch_id, journal_entry__isnull=True).select_related("customer"),
        "unposted_purchases": PurchaseInvoice.objects.filter(branch_id=branch_id, journal_entry__isnull=True).select_related("supplier"),
    })


@login_required(login_url='login')
@role_required('view_monthlyclose')
def monthly_close_list(request):
    companies = _user_companies(request.user)
    selected_company_id = request.GET.get("company") or request.session.get("company_id")
    closes = MonthlyClose.objects.filter(company__in=companies).select_related("company", "closed_by", "reopened_by")
    if selected_company_id:
        closes = closes.filter(company_id=selected_company_id)
    return render(request, 'core/monthly_close_list.html', {
        "title": "ط§ظ„ظ‚ظپظ„ ط§ظ„ط´ظ‡ط±ظٹ",
        "companies": companies.order_by("name"),
        "selected_company_id": str(selected_company_id or ""),
        "closes": closes,
    })


@login_required(login_url='login')
@role_required('close_month')
def monthly_close_add(request):
    companies = _user_companies(request.user)
    form = MonthlyCloseForm(request.POST or None, companies=companies)
    if request.method == "POST" and form.is_valid():
        monthly_close, created = MonthlyClose.objects.update_or_create(
            company=form.cleaned_data["company"],
            year=form.cleaned_data["year"],
            month=form.cleaned_data["month"],
            defaults={
                "is_closed": True,
                "closed_by": request.user,
                "reopened_by": None,
                "reopened_at": None,
                "note": form.cleaned_data.get("note", ""),
            },
        )
        message = "طھظ… ظ‚ظپظ„ ط§ظ„ط´ظ‡ط± ط¨ظ†ط¬ط§ط­." if created else "طھظ… ط¥ط¹ط§ط¯ط© ظ‚ظپظ„ ط§ظ„ط´ظ‡ط± ط¨ظ†ط¬ط§ط­."
        messages.success(request, message)
        return redirect("monthly_close_list")
    return render(request, 'core/monthly_close_form.html', {
        "title": "ظ‚ظپظ„ ط´ظ‡ط± ظ…ط­ط§ط³ط¨ظٹ",
        "form": form,
    })


@login_required(login_url='login')
@role_required('reopen_month')
def monthly_close_reopen(request, close_id):
    monthly_close = get_object_or_404(MonthlyClose, id=close_id, company__in=_user_companies(request.user))
    if request.method == "POST":
        monthly_close.is_closed = False
        monthly_close.reopened_by = request.user
        monthly_close.reopened_at = timezone.now()
        monthly_close.save(update_fields=["is_closed", "reopened_by", "reopened_at"])
        messages.success(request, "طھظ… ظپطھط­ ط§ظ„ط´ظ‡ط± ط§ظ„ظ…ط­ط§ط³ط¨ظٹ.")
    return redirect("monthly_close_list")


@login_required(login_url='login')
@role_required('view_employee')
def employee_finance_dashboard(request):
    companies = _user_companies(request.user)
    branches = _user_branches(request.user)
    employees = Employee.objects.filter(branch__in=branches)
    salaries = SalaryRecord.objects.filter(branch__in=branches)
    advances = EmployeeAdvance.objects.filter(branch__in=branches)
    return render(request, 'core/employee_finance_dashboard.html', {
        "title": "ظ…ط§ظ„ظٹط© ط§ظ„ظ…ظˆط¸ظپظٹظ†",
        "employees_count": employees.count(),
        "active_employees_count": employees.filter(status='active').count(),
        "salary_total": salaries.aggregate(total=Coalesce(Sum('net_salary'), Decimal('0')))['total'],
        "open_advances_total": advances.filter(status='open').aggregate(total=Coalesce(Sum(F('amount') - F('paid_amount')), Decimal('0')))['total'],
        "latest_salaries": salaries.select_related("employee").order_by("-year", "-month")[:6],
        "latest_advances": advances.select_related("employee").order_by("-date")[:6],
    })


@login_required(login_url='login')
@role_required('view_employee')
def employee_list(request):
    employees = Employee.objects.filter(branch__in=_user_branches(request.user)).select_related("company", "branch")
    return render(request, 'core/employee_list.html', {"title": "ط§ظ„ظ…ظˆط¸ظپظˆظ†", "employees": employees})


@login_required(login_url='login')
@role_required('add_employee')
def employee_add(request):
    form = EmployeeForm(request.POST or None, companies=_user_companies(request.user))
    form.fields["branch"].queryset = _user_branches(request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "طھظ… ط¥ط¶ط§ظپط© ط§ظ„ظ…ظˆط¸ظپ ط¨ظ†ط¬ط§ط­.")
        return redirect("employee_list")
    return render(request, 'core/employee_form.html', {"title": "ط¥ط¶ط§ظپط© ظ…ظˆط¸ظپ", "form": form})


@login_required(login_url='login')
@role_required('change_employee')
def employee_edit(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, branch__in=_user_branches(request.user))
    form = EmployeeForm(request.POST or None, instance=employee, companies=_user_companies(request.user))
    form.fields["branch"].queryset = _user_branches(request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "طھظ… طھط¹ط¯ظٹظ„ ط¨ظٹط§ظ†ط§طھ ط§ظ„ظ…ظˆط¸ظپ.")
        return redirect("employee_list")
    return render(request, 'core/employee_form.html', {"title": "طھط¹ط¯ظٹظ„ ظ…ظˆط¸ظپ", "form": form})


@login_required(login_url='login')
@role_required('view_salaryrecord')
def salary_list(request):
    salaries = SalaryRecord.objects.filter(branch__in=_user_branches(request.user)).select_related("employee", "company").order_by("-year", "-month")
    return render(request, 'core/salary_list.html', {"title": "ط±ظˆط§طھط¨ ط§ظ„ظ…ظˆط¸ظپظٹظ†", "salaries": salaries})


@login_required(login_url='login')
@role_required('add_salaryrecord')
def salary_add(request):
    form = SalaryRecordForm(request.POST or None, companies=_user_companies(request.user))
    form.fields["employee"].queryset = Employee.objects.filter(branch__in=_user_branches(request.user), status='active')
    if request.method == "POST" and form.is_valid():
        salary = form.save(commit=False)
        payment_date = salary.payment_date or timezone.localdate()
        assert_month_open(salary.employee.company, payment_date)
        salary.save()
        try:
            if salary.status == "approved":
                approve_salary(salary, payment_date)
            elif salary.status == "paid":
                pay_salary(salary, payment_date)
        except ValueError as exc:
            salary.delete()
            form.add_error("advances_deduction", str(exc))
            return render(request, 'core/salary_form.html', {"title": "ط·آ¥ط·آ¶ط·آ§ط¸ظ¾ط·آ© ط·آ±ط·آ§ط·ع¾ط·آ¨", "form": form})
        messages.success(request, "ط·ع¾ط¸â€¦ ط·آ­ط¸ظ¾ط·آ¸ ط¸â€¦ط·آ³ط¸ظ¹ط·آ± ط·آ§ط¸â€‍ط·آ±ط·آ§ط·ع¾ط·آ¨.")
        return redirect("salary_list")
    employees = Employee.objects.filter(branch__in=_user_branches(request.user), status='active')
    salary_defaults = {}
    for employee in employees:
        open_advances = EmployeeAdvance.objects.filter(employee=employee, status='open').aggregate(
            total=Coalesce(Sum(F('amount') - F('paid_amount')), Decimal('0'))
        )['total']
        salary_defaults[str(employee.id)] = {
            "basic_salary": str(employee.basic_salary),
            "allowances": str(employee.housing_allowance + employee.transport_allowance + employee.other_allowances),
            "open_advances": str(open_advances),
        }
    return render(request, 'core/salary_form.html', {
        "title": "Add Salary",
        "form": form,
        "salary_defaults_json": json.dumps(salary_defaults),
    })


@login_required(login_url='login')
@role_required('change_salaryrecord')
def salary_approve(request, salary_id):
    salary = get_object_or_404(SalaryRecord, id=salary_id, branch__in=_user_branches(request.user))
    if request.method == "POST":
        try:
            entry = approve_salary(salary)
            messages.success(request, f"طھظ… ط§ط¹طھظ…ط§ط¯ ط§ظ„ط±ط§طھط¨ ظˆط¥ظ†ط´ط§ط، ظ‚ظٹط¯ ط±ظ‚ظ… {entry.id}.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("salary_list")


@login_required(login_url='login')
@role_required('change_salaryrecord')
def salary_pay(request, salary_id):
    salary = get_object_or_404(SalaryRecord, id=salary_id, branch__in=_user_branches(request.user))
    if request.method == "POST":
        try:
            entry = pay_salary(salary)
            messages.success(request, f"طھظ… ط¯ظپط¹ ط§ظ„ط±ط§طھط¨ ظˆط¥ظ†ط´ط§ط، ظ‚ظٹط¯ ط±ظ‚ظ… {entry.id}.")
        except ValueError as exc:
            messages.error(request, str(exc))
    return redirect("salary_list")


@login_required(login_url='login')
@role_required('view_employeeadvance')
def advance_list(request):
    advances = EmployeeAdvance.objects.filter(branch__in=_user_branches(request.user)).select_related("employee", "company")
    return render(request, 'core/advance_list.html', {"title": "ط³ظ„ظپ ط§ظ„ظ…ظˆط¸ظپظٹظ†", "advances": advances})


@login_required(login_url='login')
@role_required('add_employeeadvance')
def advance_add(request):
    form = EmployeeAdvanceForm(request.POST or None, companies=_user_companies(request.user))
    form.fields["employee"].queryset = Employee.objects.filter(branch__in=_user_branches(request.user), status='active')
    if request.method == "POST" and form.is_valid():
        advance = form.save(commit=False)
        assert_month_open(advance.employee.company, advance.date)
        advance.save()
        entry = create_balanced_entry(
            branch=advance.branch or Branch.objects.filter(company=advance.company).first(),
            date=advance.date,
            description=f"ط³ظ„ظپط© ظ…ظˆط¸ظپ: {advance.employee.name}",
            lines=[
                {"account": "1300", "debit": advance.amount, "note": "ط³ظ„ظپط© ظ…ظˆط¸ظپ"},
                {"account": "1000", "credit": advance.amount, "note": "طµط±ظپ ط³ظ„ظپط©"},
            ],
        )
        advance.journal_entry = entry
        advance.save(update_fields=["journal_entry"])
        messages.success(request, "طھظ… طھط³ط¬ظٹظ„ ط§ظ„ط³ظ„ظپط© ظˆطھط±ط­ظٹظ„ظ‡ط§ ظ…ط­ط§ط³ط¨ظٹط§ظ‹.")
        return redirect("advance_list")
    return render(request, 'core/advance_form.html', {"title": "ط¥ط¶ط§ظپط© ط³ظ„ظپط©", "form": form})


@login_required(login_url='login')
@role_required('view_invoice')
def export_sales_csv(request):
    branch_id = request.session.get('branch_id')
    if not branch_id:
        return redirect('select_company_branch')

    from invoicing.models import Invoice

    date_from, date_to = _date_range_from_request(request)
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="sales-report.csv"'
    writer = csv.writer(response)
    writer.writerow(['Invoice No', 'Customer', 'Date', 'Subtotal', 'VAT', 'Total', 'Payment', 'Posted'])
    invoices = Invoice.objects.select_related('customer').filter(
        branch_id=branch_id,
        issue_date__date__range=[date_from, date_to],
    ).order_by('issue_date')
    for invoice in invoices:
        writer.writerow([
            invoice.invoice_number,
            invoice.customer.name,
            invoice.issue_date.strftime('%Y-%m-%d'),
            invoice.total_amount,
            invoice.total_vat,
            invoice.total_with_vat,
            invoice.payment_method,
            'Yes' if invoice.is_posted else 'No',
        ])
    return response


# ============================
#  User Registration (Signup)
# ============================
def signup(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()

            # ط¥ظ†ط´ط§ط، ظ…ظ„ظپ طھط¹ط±ظٹظپ ط§ظ„ظ…ط³طھط®ط¯ظ… (Profile) ظˆط±ط¨ط·ظ‡ ط¨ط±ظ‚ظ… ط§ظ„ظ‡ظˆظٹط©
            UserProfile.objects.create(
                user=user,
                national_id=form.cleaned_data['national_id'],
                phone=form.cleaned_data.get('phone'),
                role=form.cleaned_data.get('role'),
            )

            login(request, user)
            messages.success(request, "طھظ… ط¥ظ†ط´ط§ط، ط§ظ„ط­ط³ط§ط¨. ط£ظƒظ…ظ„ ط¨ظٹط§ظ†ط§طھ ط§ظ„ط´ط±ظƒط© ظˆط£ط±ظپظ‚ ط¥ظٹطµط§ظ„ ط§ظ„طھط­ظˆظٹظ„ ظ„طھظپط¹ظٹظ„ ط§ظ„ط§ط´طھط±ط§ظƒ.")
            return redirect('company_add')
    else:
        form = UserRegistrationForm()
    return render(request, 'core/signup.html', {
        'form': form, "title": "ط¥ظ†ط´ط§ط، ط­ط³ط§ط¨ ط¬ط¯ظٹط¯"
    })


# ============================
#  Accounts
# ============================
@login_required(login_url='login')
@role_required('view_account')
def accounts_list(request):
    accounts = Account.objects.all().order_by('code') # _("Accounts List")
    return render(request, 'core/accounts_list.html', {"accounts": accounts, "title": "ط¯ظ„ظٹظ„ ط§ظ„ط­ط³ط§ط¨ط§طھ"})


# ============================
#  Journal Entries List
# ============================
@login_required(login_url='login')
@role_required('view_journalentry')
def journal_list(request):
    branch_id = request.session.get('branch_id') # _("Journal Entries List")
    entries = JournalEntry.objects.filter(branch_id=branch_id).order_by('-date', '-id') # _("Journal Entries List")
    return render(request, 'core/journal_list.html', {"entries": entries, "title": "ظ‚ظٹظˆط¯ ط§ظ„ظٹظˆظ…ظٹط©"})


# ============================
#  Add Journal Entry (Double Entry)
# ============================
@login_required(login_url='login')
@role_required('add_journalentry')
def journal_add(request):
    branch_id = request.session.get('branch_id')

    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        formset = JournalEntryLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            entry = form.save(commit=False)
            entry.branch_id = branch_id
            assert_month_open(entry.branch.company, entry.date)
            entry.save()

            lines = formset.save(commit=False)
            for line in lines:
                if (line.debit or line.credit) and line.account:
                    line.entry = entry
                    line.save()

            return redirect('journal_list')

    else:
        form = JournalEntryForm()
        formset = JournalEntryLineFormSet()

    return render(request, 'core/journal_form.html', {
        "form": form,
        "formset": formset,
        "mode": "create",
        "accounts": Account.objects.all().order_by("code"),
        "title": "ط¥ط¶ط§ظپط© ظ‚ظٹط¯"
    })


# ============================
#  Edit Journal Entry
# ============================
@login_required(login_url='login')
@role_required('change_journalentry')
def journal_edit(request, pk):
    branch_id = request.session.get('branch_id')
    entry = get_object_or_404(JournalEntry, pk=pk, branch_id=branch_id)

    if request.method == 'POST':
        form = JournalEntryForm(request.POST, instance=entry)
        formset = JournalEntryLineFormSet(request.POST, instance=entry)

        if form.is_valid() and formset.is_valid():
            edited_entry = form.save(commit=False)
            assert_month_open(edited_entry.branch.company, edited_entry.date)
            edited_entry.save()
            formset.save()
            return redirect('journal_list')

    else:
        form = JournalEntryForm(instance=entry)
        formset = JournalEntryLineFormSet(instance=entry)

    return render(request, 'core/journal_form.html', {
        "form": form,
        "formset": formset,
        "mode": "edit",
        "entry": entry,
        "accounts": Account.objects.all().order_by("code"),
        "title": "طھط¹ط¯ظٹظ„ ظ‚ظٹط¯"
    })


# ============================
#  Companies
# ============================
@login_required(login_url='login')
def company_add(request):
    if request.method == 'POST':
        form = CompanySubscriptionRequestForm(request.POST, request.FILES)
        if request.user.is_superuser:
            form.fields["requested_role"].queryset = Role.objects.all()
        if form.is_valid():
            plan = form.cleaned_data.get("plan")
            if not plan:
                form.add_error("plan", "ط§ط®طھط± ط¨ط§ظ‚ط© ط§ظ„ط§ط´طھط±ط§ظƒ ظ‚ط¨ظ„ ط¥ط±ط³ط§ظ„ ط§ظ„ط·ظ„ط¨.")
                return render(request, 'core/company_form.html', {
                    "form": form, "title": "ط¥ط¶ط§ظپط© ط´ط±ظƒط©"
                })
            owned_company_count = Company.objects.filter(
                owner=request.user,
                subscription_status__in=["pending", "active"],
            ).count()
            if owned_company_count >= plan.max_companies:
                form.add_error("plan", f"ظ‡ط°ظ‡ ط§ظ„ط¨ط§ظ‚ط© طھط³ظ…ط­ ط¨ط¥ط¶ط§ظپط© {plan.max_companies} ط´ط±ظƒط© ظپظ‚ط·.")
                return render(request, 'core/company_form.html', {
                    "form": form, "title": "ط¥ط¶ط§ظپط© ط´ط±ظƒط©"
                })
            company = form.save(commit=False)
            company.owner = request.user
            company.owner_role = form.cleaned_data.get("requested_role")
            company.subscription_status = "pending"
            company.save()

            owner_role = form.cleaned_data.get("requested_role")
            if not owner_role:
                owner_role, _ = Role.objects.get_or_create(
                    name="ظ…ط§ظ„ظƒ ط§ظ„ط´ط±ظƒط©",
                    defaults={
                        "description": "طµظ„ط§ط­ظٹط§طھ ظ…ط§ظ„ظƒ ط§ظ„ط´ط±ظƒط© ط¯ط§ط®ظ„ ط´ط±ظƒطھظ‡.",
                        "requires_subscription": True,
                    }
                )
                company.owner_role = owner_role
                company.save(update_fields=["owner_role"])

            CompanyMembership.objects.get_or_create(
                user=request.user,
                company=company,
                defaults={"role": owner_role, "is_active": True},
            )

            SubscriptionRequest.objects.create(
                user=request.user,
                plan=plan,
                company=company,
                requested_role=owner_role,
                bank_name=form.cleaned_data["bank_name"],
                transfer_reference=form.cleaned_data.get("transfer_reference", ""),
                transfer_notice=form.cleaned_data["transfer_notice"],
            )
            messages.success(request, "طھظ… طھط³ط¬ظٹظ„ ط§ظ„ط´ط±ظƒط© ظˆط¥ط±ط³ط§ظ„ ط·ظ„ط¨ ط§ظ„ط§ط´طھط±ط§ظƒ ظ„ظ„ظ…ط±ط§ط¬ط¹ط©.")
            return redirect('company_list')
    else:
        form = CompanySubscriptionRequestForm()
    if request.user.is_superuser:
        form.fields["requested_role"].queryset = Role.objects.all()

    return render(request, 'core/company_form.html', {
        "form": form, "title": "ط¥ط¶ط§ظپط© ط´ط±ظƒط©"
    })

@login_required(login_url='login')
def company_list(request):
    companies = list(_user_companies(request.user).select_related("owner", "owner_role"))
    company_rows = []
    for company in companies:
        can_view_branches = _can_view_company_branches(request.user, company)
        can_add_branch = _can_add_branch_to_company(request.user, company)
        branch_count = _user_branches(request.user).filter(company=company).count() if can_view_branches else 0
        company_rows.append({
            "company": company,
            "branch_count": branch_count,
            "can_view_branches": can_view_branches,
            "can_add_branch": can_add_branch,
        })
    return render(request, 'core/company_list.html', {
        "companies": companies,
        "company_rows": company_rows,
        "can_view_any_branches": any(row["can_view_branches"] for row in company_rows),
        "can_add_any_branch": any(row["can_add_branch"] for row in company_rows),
        "title": "ط§ظ„ط´ط±ظƒط§طھ",
    })



@login_required(login_url='login')
def company_access(request):
    if _user_companies(request.user).exists():
        return redirect('select_company_branch')
    return render(request, 'core/company_access.html', {
        "title": "ط§ظ„ظˆطµظˆظ„ ط¥ظ„ظ‰ ط´ط±ظƒط©",
        "pending_requests": CompanyJoinRequest.objects.filter(user=request.user, status='pending').select_related('company'),
    })


@login_required(login_url='login')
def company_join_request(request):
    found_company = None
    if request.method == "POST":
        unified_number = request.POST.get("unified_number")
        found_company = Company.objects.filter(unified_number=unified_number).select_related("owner").first()
    form = CompanyJoinRequestForm(request.POST or None, company=found_company)
    if request.method == "POST" and form.is_valid():
        if not found_company:
            form.add_error("unified_number", "ظ„ط§ طھظˆط¬ط¯ ط´ط±ظƒط© ط¨ظ‡ط°ط§ ط§ظ„ط±ظ‚ظ… ط§ظ„ظ…ظˆط­ط¯.")
        elif found_company.owner_id == request.user.id or CompanyMembership.objects.filter(user=request.user, company=found_company, is_active=True).exists():
            messages.info(request, "ط£ظ†طھ ظ…ط±طھط¨ط· ط¨ظ‡ط°ظ‡ ط§ظ„ط´ط±ظƒط© ط¨ط§ظ„ظپط¹ظ„.")
            return redirect("select_company_branch")
        elif "submit_request" in request.POST:
            join_request, created = CompanyJoinRequest.objects.get_or_create(
                user=request.user,
                company=found_company,
                status="pending",
                defaults={
                    "requested_role": form.cleaned_data.get("requested_role"),
                    "requested_branch": form.cleaned_data.get("requested_branch"),
                    "note": form.cleaned_data.get("note", ""),
                }
            )
            messages.success(request, "طھظ… ط¥ط±ط³ط§ظ„ ط·ظ„ط¨ ط§ظ„ط§ظ†ط¶ظ…ط§ظ… ط¥ظ„ظ‰ ظ…ط§ظ„ظƒ ط§ظ„ط´ط±ظƒط©." if created else "ظ„ط¯ظٹظƒ ط·ظ„ط¨ ط§ظ†ط¶ظ…ط§ظ… ظ‚ظٹط¯ ط§ظ„ظ…ط±ط§ط¬ط¹ط© ظ„ظ‡ط°ظ‡ ط§ظ„ط´ط±ظƒط©.")
            return redirect("company_access")
    return render(request, 'core/company_join_request.html', {"form": form, "found_company": found_company, "title": "ط·ظ„ط¨ ط§ظ„ط§ظ†ط¶ظ…ط§ظ… ط¥ظ„ظ‰ ط´ط±ظƒط©"})


@login_required(login_url='login')
def company_join_requests(request):
    requests = CompanyJoinRequest.objects.filter(company__owner=request.user, status="pending").select_related("user", "company", "requested_role", "requested_branch").order_by("-created_at")
    return render(request, 'core/company_join_requests.html', {"requests": requests, "title": "ط·ظ„ط¨ط§طھ ط§ظ„ط§ظ†ط¶ظ…ط§ظ… ظ„ظ„ط´ط±ظƒط§طھ"})


@login_required(login_url='login')
def company_join_review(request, request_id, decision):
    join_request = get_object_or_404(CompanyJoinRequest, id=request_id, company__owner=request.user, status="pending")
    join_request.reviewed_by = request.user
    join_request.reviewed_at = timezone.now()
    if decision == "approve":
        active_plan = join_request.company.active_plan
        if active_plan and active_plan.max_users:
            active_members_count = CompanyMembership.objects.filter(company=join_request.company, is_active=True).count()
            if active_members_count >= active_plan.max_users:
                messages.error(request, f"ظ„ط§ ظٹظ…ظƒظ† ظ‚ط¨ظˆظ„ ط§ظ„ط·ظ„ط¨ط› ط¨ط§ظ‚ط© ط§ظ„ط´ط±ظƒط© طھط³ظ…ط­ ط¨ظ€ {active_plan.max_users} ظ…ط³طھط®ط¯ظ… ظپظ‚ط·.")
                return redirect("company_join_requests")
        join_request.status = "approved"
        CompanyMembership.objects.update_or_create(
            user=join_request.user,
            company=join_request.company,
            defaults={"role": join_request.requested_role or join_request.company.owner_role, "branch": join_request.requested_branch, "is_active": True},
        )
        messages.success(request, "طھظ… ظ‚ط¨ظˆظ„ ط·ظ„ط¨ ط§ظ„ط§ظ†ط¶ظ…ط§ظ… ظˆط±ط¨ط· ط§ظ„ظ…ط³طھط®ط¯ظ… ط¨ط§ظ„ط´ط±ظƒط©.")
    else:
        join_request.status = "rejected"
        messages.success(request, "طھظ… ط±ظپط¶ ط·ظ„ط¨ ط§ظ„ط§ظ†ط¶ظ…ط§ظ….")
    join_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    return redirect("company_join_requests")


@login_required(login_url='login')
# ============================
#  Branches
# ============================
def branch_list(request):
    branches = _user_branches(request.user).select_related('company')
    selected_company = None
    company_id = request.GET.get("company")
    if company_id:
        selected_company = get_object_or_404(_user_companies(request.user), id=company_id)
        branches = branches.filter(company=selected_company)
    return render(request, 'core/branch_list.html', {
        "branches": branches,
        "selected_company": selected_company,
        "can_add_branch": _can_add_branch_to_company(request.user, selected_company) if selected_company else _user_companies(request.user).exists(),
        "title": "ط§ظ„ظپط±ظˆط¹",
    })

@login_required(login_url='login')

def branch_add(request):
    initial_company = None
    company_id = request.GET.get("company")
    if company_id:
        initial_company = get_object_or_404(_user_companies(request.user), id=company_id)
        if not _can_add_branch_to_company(request.user, initial_company):
            messages.error(request, "لا تملك صلاحية إضافة فرع لهذه الشركة.")
            return redirect("company_list")
    if request.method == 'POST':
        form = BranchForm(request.POST) # _("Add Branch")
        form.fields['company'].queryset = _user_companies(request.user)
        if form.is_valid():
            company = form.cleaned_data["company"]
            if not _can_add_branch_to_company(request.user, company):
                form.add_error("company", "لا تملك صلاحية إضافة فرع لهذه الشركة.")
                return render(request, 'core/branch_form.html', {
                    "form": form, "title": "ط¥ط¶ط§ظپط© ظپط±ط¹"
                })
            form.save()
            return redirect('branch_list')
    else:
        form = BranchForm(initial={"company": initial_company} if initial_company else None)
        form.fields['company'].queryset = _user_companies(request.user)

    return render(request, 'core/branch_form.html', {
        "form": form, "title": "ط¥ط¶ط§ظپط© ظپط±ط¹"
    })

@login_required(login_url='login')

def branch_edit(request, id):
    branch = get_object_or_404(_user_branches(request.user), id=id)

    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        form.fields['company'].queryset = _user_companies(request.user)
        if form.is_valid():
            form.save()
            return redirect('branch_list') # _("Edit Branch")
    else:
        form = BranchForm(instance=branch)
        form.fields['company'].queryset = _user_companies(request.user)

    return render(request, 'core/branch_form.html', {
        "form": form,
        "title": "طھط¹ط¯ظٹظ„ ظپط±ط¹"
    })


def branch_delete(request, id):
    branch = get_object_or_404(_user_branches(request.user), id=id)
    branch.delete()
    return redirect('branch_list')


# ============================
#  ط§ط®طھظٹط§ط± ط§ظ„ط´ط±ظƒط© ظˆط§ظ„ظپط±ط¹
# ============================
@login_required(login_url='login')
def select_company_branch(request): # _("Select Company and Branch")
    companies = _user_companies(request.user)
    if not companies.exists():
        return redirect('company_access')
    branches = user_accessible_branches(request.user).filter(company__in=companies)

    if request.method == "POST":
        company_id = request.POST.get("company_id")
        branch_id = request.POST.get("branch_id")
        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or "dashboard"
        if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            next_url = "dashboard"

        company = get_object_or_404(companies, id=company_id)
        # ط§ظ„طھط£ظƒط¯ ظ…ظ† ط£ظ† ط§ظ„ظپط±ط¹ ظٹطھط¨ط¹ ظ„ظ„ط´ط±ظƒط© ط§ظ„ظ…ط®طھط§ط±ط©
        branch = get_object_or_404(branches, id=branch_id, company=company)
        if not user_can_access_branch(request.user, branch):
            messages.error(request, "لا تملك صلاحية الوصول إلى هذا الفرع.")
            return redirect("select_company_branch")

        request.session['company_id'] = company.id
        request.session['company_name'] = company.name

        request.session['branch_id'] = branch.id
        request.session['branch_name'] = branch.name

        return redirect(next_url)

    return render(request, 'core/select_company_branch.html', {
        "companies": companies.order_by('name'),
        "branches": branches.select_related('company').order_by('company__name', 'name'),
        "title": "ط§ط®طھظٹط§ط± ط§ظ„ط´ط±ظƒط© ظˆط§ظ„ظپط±ط¹"
    }) # _("Select Company and Branch")


@login_required(login_url='login')
@role_required('add_journalentry')
# ============================
#  Copy Journal Entry
# ============================
def journal_copy(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    assert_month_open(entry.branch.company, entry.date)
    new_entry = JournalEntry.objects.create(
        date=entry.date,
        description=entry.description,
        branch=entry.branch,
    )

    for line in entry.lines.all():
        JournalEntryLine.objects.create(
            entry=new_entry,
            account=line.account,
            debit=line.debit,
            credit=line.credit,
            note=line.note
        )

    return redirect('journal_edit', new_entry.id)


@login_required(login_url='login')
@role_required('view_journalentry')
# ============================
#  Journal PDF
# ============================
def journal_pdf(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    return render(request, "core/journal_pdf.html", {"entry": entry, "title": "ط·ط¨ط§ط¹ط© ط§ظ„ظ‚ظٹط¯"})

@login_required(login_url='login')
@role_required('add_account')
def account_add(request):
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('accounts_list')  # ط¹ط¯ظ‘ظ„ ط§ظ„ط§ط³ظ… ط­ط³ط¨ طµظپط­ط© ط§ظ„ظ‚ط§ط¦ظ…ط©
    else:
        form = AccountForm()
    return render(request, 'core/account_form.html', {
        "form": form, "title": "ط¥ط¶ط§ظپط© ط­ط³ط§ط¨"
    })
   
