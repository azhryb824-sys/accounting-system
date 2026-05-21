import csv
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login
from .models import Account, JournalEntry, Company, Branch, CompanyJoinRequest, CompanyMembership, Employee, EmployeeAdvance, JournalEntryLine, MonthlyClose, SalaryRecord
from .forms import CompanyForm, CompanyJoinRequestForm, CompanySubscriptionRequestForm, BranchForm, JournalEntryForm, JournalEntryLineFormSet, AccountForm, MonthlyCloseForm, EmployeeForm, SalaryRecordForm, EmployeeAdvanceForm
from .services.accounting import create_balanced_entry
from .services.monthly_close import assert_month_open
from accounts.forms import UserRegistrationForm
from accounts.models import Role, SubscriptionRequest, UserProfile
from accounts.views import role_required

# ============================
#  Home Page (Landing)
# ============================
def home(request):
    """الصفحة الرئيسية التي تظهر قبل تسجيل الدخول"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/home.html', {
        "title": "مرحباً بك في نظام المحاسبة الذكي",
    })


# ============================
#  Dashboard
# ============================
@login_required(login_url='login')
def dashboard(request):
    branch_id = request.session.get('branch_id')

    # إذا لم يتم اختيار فرع، وجه المستخدم لصفحة الاختيار
    if not branch_id: # _("If no branch is selected, redirect the user to the selection page")
        if not _user_companies(request.user).exists():
            return redirect('company_access')
        return redirect('select_company_branch')

    context = {
        "accounts_count": Account.objects.count(),
        "entries_count": JournalEntry.objects.filter(branch_id=branch_id).count(),
        "branch_name": request.session.get("branch_name"),
        "company_name": request.session.get("company_name"),
        "title": "لوحة التحكم",
    }
    from invoicing.models import Invoice, Item, PurchaseInvoice

    invoices = Invoice.objects.filter(branch_id=branch_id)
    purchases = PurchaseInvoice.objects.filter(branch_id=branch_id)
    items = Item.objects.filter(branch_id=branch_id)
    salaries = SalaryRecord.objects.filter(branch_id=branch_id)
    advances = EmployeeAdvance.objects.filter(branch_id=branch_id, status='open')
    today = timezone.localdate()
    salary_total = salaries.aggregate(total=Coalesce(Sum('net_salary'), Decimal('0')))['total']
    advances_total = advances.aggregate(total=Coalesce(Sum(F('amount') - F('paid_amount')), Decimal('0')))['total']
    context.update({
        "invoices_count": invoices.count(),
        "today_invoices_count": invoices.filter(issue_date__date=today).count(),
        "sales_total": invoices.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'],
        "purchases_total": purchases.aggregate(total=Coalesce(Sum('total_with_vat'), Decimal('0')))['total'],
        "salary_total": salary_total,
        "employee_advances_total": advances_total,
        "operating_result": invoices.aggregate(total=Coalesce(Sum('total_amount'), Decimal('0')))['total'] - purchases.aggregate(total=Coalesce(Sum('total_before_vat'), Decimal('0')))['total'] - salary_total,
        "inventory_value": items.aggregate(total=Coalesce(Sum(F('quantity') * F('cost')), Decimal('0')))['total'],
        "low_stock_count": items.filter(quantity__lte=F('min_quantity'), is_active=True).count(),
        "low_stock_items": items.filter(quantity__lte=F('min_quantity'), is_active=True).order_by('quantity')[:6],
    })
    return render(request, 'core/dashboard.html', context)


def _user_companies(user):
    if user.is_superuser:
        return Company.objects.all()
    member_company_ids = CompanyMembership.objects.filter(user=user, is_active=True).values_list('company_id', flat=True)
    return Company.objects.filter(Q(owner=user) | Q(id__in=member_company_ids)).distinct()

# ============================
#  Reports Center
# ============================
def _date_range_from_request(request):
    today = timezone.localdate()
    date_from = request.GET.get('from') or today.replace(day=1).isoformat()
    date_to = request.GET.get('to') or today.isoformat()
    return date_from, date_to


@login_required(login_url='login')
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
        "title": "مركز التقارير",
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
@role_required('view_monthlyclose')
def monthly_close_list(request):
    companies = _user_companies(request.user)
    selected_company_id = request.GET.get("company") or request.session.get("company_id")
    closes = MonthlyClose.objects.filter(company__in=companies).select_related("company", "closed_by", "reopened_by")
    if selected_company_id:
        closes = closes.filter(company_id=selected_company_id)
    return render(request, 'core/monthly_close_list.html', {
        "title": "القفل الشهري",
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
        message = "تم قفل الشهر بنجاح." if created else "تم إعادة قفل الشهر بنجاح."
        messages.success(request, message)
        return redirect("monthly_close_list")
    return render(request, 'core/monthly_close_form.html', {
        "title": "قفل شهر محاسبي",
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
        messages.success(request, "تم فتح الشهر المحاسبي.")
    return redirect("monthly_close_list")


@login_required(login_url='login')
@role_required('view_employee')
def employee_finance_dashboard(request):
    companies = _user_companies(request.user)
    employees = Employee.objects.filter(company__in=companies)
    salaries = SalaryRecord.objects.filter(company__in=companies)
    advances = EmployeeAdvance.objects.filter(company__in=companies)
    return render(request, 'core/employee_finance_dashboard.html', {
        "title": "مالية الموظفين",
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
    employees = Employee.objects.filter(company__in=_user_companies(request.user)).select_related("company", "branch")
    return render(request, 'core/employee_list.html', {"title": "الموظفون", "employees": employees})


@login_required(login_url='login')
@role_required('add_employee')
def employee_add(request):
    form = EmployeeForm(request.POST or None, companies=_user_companies(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم إضافة الموظف بنجاح.")
        return redirect("employee_list")
    return render(request, 'core/employee_form.html', {"title": "إضافة موظف", "form": form})


@login_required(login_url='login')
@role_required('change_employee')
def employee_edit(request, employee_id):
    employee = get_object_or_404(Employee, id=employee_id, company__in=_user_companies(request.user))
    form = EmployeeForm(request.POST or None, instance=employee, companies=_user_companies(request.user))
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "تم تعديل بيانات الموظف.")
        return redirect("employee_list")
    return render(request, 'core/employee_form.html', {"title": "تعديل موظف", "form": form})


@login_required(login_url='login')
@role_required('view_salaryrecord')
def salary_list(request):
    salaries = SalaryRecord.objects.filter(company__in=_user_companies(request.user)).select_related("employee", "company").order_by("-year", "-month")
    return render(request, 'core/salary_list.html', {"title": "رواتب الموظفين", "salaries": salaries})


@login_required(login_url='login')
@role_required('add_salaryrecord')
def salary_add(request):
    form = SalaryRecordForm(request.POST or None, companies=_user_companies(request.user))
    if request.method == "POST" and form.is_valid():
        salary = form.save(commit=False)
        payment_date = salary.payment_date or timezone.localdate()
        assert_month_open(salary.employee.company, payment_date)
        salary.save()
        if salary.status in {"approved", "paid"}:
            credit_account = "1000" if salary.status == "paid" else "2300"
            credit_note = "صرف راتب" if salary.status == "paid" else "رواتب مستحقة"
            create_balanced_entry(
                branch=salary.branch or Branch.objects.filter(company=salary.company).first(),
                date=payment_date,
                description=f"راتب {salary.employee.name} عن {salary.period_label}",
                lines=[
                    {"account": "5200", "debit": salary.net_salary, "note": "مصروف راتب"},
                    {"account": credit_account, "credit": salary.net_salary, "note": credit_note},
                ],
            )
        messages.success(request, "تم حفظ مسير الراتب.")
        return redirect("salary_list")
    return render(request, 'core/salary_form.html', {"title": "إضافة راتب", "form": form})


@login_required(login_url='login')
@role_required('view_employeeadvance')
def advance_list(request):
    advances = EmployeeAdvance.objects.filter(company__in=_user_companies(request.user)).select_related("employee", "company")
    return render(request, 'core/advance_list.html', {"title": "سلف الموظفين", "advances": advances})


@login_required(login_url='login')
@role_required('add_employeeadvance')
def advance_add(request):
    form = EmployeeAdvanceForm(request.POST or None, companies=_user_companies(request.user))
    if request.method == "POST" and form.is_valid():
        advance = form.save(commit=False)
        assert_month_open(advance.employee.company, advance.date)
        advance.save()
        create_balanced_entry(
            branch=advance.branch or Branch.objects.filter(company=advance.company).first(),
            date=advance.date,
            description=f"سلفة موظف: {advance.employee.name}",
            lines=[
                {"account": "1300", "debit": advance.amount, "note": "سلفة موظف"},
                {"account": "1000", "credit": advance.amount, "note": "صرف سلفة"},
            ],
        )
        messages.success(request, "تم تسجيل السلفة وترحيلها محاسبياً.")
        return redirect("advance_list")
    return render(request, 'core/advance_form.html', {"title": "إضافة سلفة", "form": form})


@login_required(login_url='login')
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

            # إنشاء ملف تعريف المستخدم (Profile) وربطه برقم الهوية
            UserProfile.objects.create(
                user=user,
                national_id=form.cleaned_data['national_id'],
                phone=form.cleaned_data.get('phone'),
                role=form.cleaned_data.get('role'),
            )

            login(request, user)
            messages.success(request, "تم إنشاء الحساب. أكمل بيانات الشركة وأرفق إيصال التحويل لتفعيل الاشتراك.")
            return redirect('company_add')
    else:
        form = UserRegistrationForm()
    return render(request, 'core/signup.html', {
        'form': form, "title": "إنشاء حساب جديد"
    })


# ============================
#  Accounts
# ============================
@login_required(login_url='login')
def accounts_list(request):
    accounts = Account.objects.all().order_by('code') # _("Accounts List")
    return render(request, 'core/accounts_list.html', {"accounts": accounts, "title": "دليل الحسابات"})


# ============================
#  Journal Entries List
# ============================
@login_required(login_url='login')
def journal_list(request):
    branch_id = request.session.get('branch_id') # _("Journal Entries List")
    entries = JournalEntry.objects.filter(branch_id=branch_id).order_by('-date', '-id') # _("Journal Entries List")
    return render(request, 'core/journal_list.html', {"entries": entries, "title": "قيود اليومية"})


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
        "title": "إضافة قيد"
    })


# ============================
#  Edit Journal Entry
# ============================
@login_required(login_url='login')
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
        "title": "تعديل قيد"
    })


# ============================
#  Companies
# ============================
@login_required(login_url='login')
def company_add(request):
    if request.method == 'POST':
        form = CompanySubscriptionRequestForm(request.POST, request.FILES)
        if form.is_valid():
            plan = form.cleaned_data["plan"]
            owned_company_count = Company.objects.filter(
                owner=request.user,
                subscription_status__in=["pending", "active"],
            ).count()
            if owned_company_count >= plan.max_companies:
                form.add_error("plan", f"هذه الباقة تسمح بإضافة {plan.max_companies} شركة فقط.")
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
                    name="مالك الشركة",
                    defaults={
                        "description": "صلاحيات مالك الشركة داخل شركته.",
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
            messages.success(request, "تم تسجيل الشركة وإرسال طلب الاشتراك للمراجعة.")
            return redirect('company_list')
    else:
        form = CompanySubscriptionRequestForm()

    return render(request, 'core/company_form.html', {
        "form": form, "title": "إضافة شركة"
    })

@login_required(login_url='login')
def company_list(request):
    companies = _user_companies(request.user)
    return render(request, 'core/company_list.html', {"companies": companies, "title": "الشركات"})



@login_required(login_url='login')
def company_access(request):
    if _user_companies(request.user).exists():
        return redirect('select_company_branch')
    return render(request, 'core/company_access.html', {
        "title": "الوصول إلى شركة",
        "pending_requests": CompanyJoinRequest.objects.filter(user=request.user, status='pending').select_related('company'),
    })


@login_required(login_url='login')
def company_join_request(request):
    form = CompanyJoinRequestForm(request.POST or None)
    found_company = None
    if request.method == "POST" and form.is_valid():
        found_company = Company.objects.filter(unified_number=form.cleaned_data["unified_number"]).select_related("owner").first()
        if not found_company:
            form.add_error("unified_number", "لا توجد شركة بهذا الرقم الموحد.")
        elif found_company.owner_id == request.user.id or CompanyMembership.objects.filter(user=request.user, company=found_company, is_active=True).exists():
            messages.info(request, "أنت مرتبط بهذه الشركة بالفعل.")
            return redirect("select_company_branch")
        elif "submit_request" in request.POST:
            join_request, created = CompanyJoinRequest.objects.get_or_create(
                user=request.user,
                company=found_company,
                status="pending",
                defaults={
                    "requested_role": form.cleaned_data.get("requested_role"),
                    "note": form.cleaned_data.get("note", ""),
                }
            )
            messages.success(request, "تم إرسال طلب الانضمام إلى مالك الشركة." if created else "لديك طلب انضمام قيد المراجعة لهذه الشركة.")
            return redirect("company_access")
    return render(request, 'core/company_join_request.html', {"form": form, "found_company": found_company, "title": "طلب الانضمام إلى شركة"})


@login_required(login_url='login')
def company_join_requests(request):
    requests = CompanyJoinRequest.objects.filter(company__owner=request.user, status="pending").select_related("user", "company", "requested_role").order_by("-created_at")
    return render(request, 'core/company_join_requests.html', {"requests": requests, "title": "طلبات الانضمام للشركات"})


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
                messages.error(request, f"لا يمكن قبول الطلب؛ باقة الشركة تسمح بـ {active_plan.max_users} مستخدم فقط.")
                return redirect("company_join_requests")
        join_request.status = "approved"
        CompanyMembership.objects.update_or_create(
            user=join_request.user,
            company=join_request.company,
            defaults={"role": join_request.requested_role or join_request.company.owner_role, "is_active": True},
        )
        messages.success(request, "تم قبول طلب الانضمام وربط المستخدم بالشركة.")
    else:
        join_request.status = "rejected"
        messages.success(request, "تم رفض طلب الانضمام.")
    join_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    return redirect("company_join_requests")


@login_required(login_url='login')
# ============================
#  Branches
# ============================
def branch_list(request):
    branches = Branch.objects.select_related('company').all()
    return render(request, 'core/branch_list.html', {"branches": branches, "title": "الفروع"})

@login_required(login_url='login')

def branch_add(request):
    if request.method == 'POST':
        form = BranchForm(request.POST) # _("Add Branch")
        if form.is_valid():
            form.save()
            return redirect('branch_list')
    else:
        form = BranchForm()

    return render(request, 'core/branch_form.html', {
        "form": form, "title": "إضافة فرع"
    })

@login_required(login_url='login')

def branch_edit(request, id):
    branch = get_object_or_404(Branch, id=id)

    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            return redirect('branch_list') # _("Edit Branch")
    else:
        form = BranchForm(instance=branch)

    return render(request, 'core/branch_form.html', {
        "form": form,
        "title": "تعديل فرع"
    })


def branch_delete(request, id):
    branch = get_object_or_404(Branch, id=id)
    branch.delete()
    return redirect('branch_list')


# ============================
#  اختيار الشركة والفرع
# ============================
@login_required(login_url='login')
def select_company_branch(request): # _("Select Company and Branch")
    companies = _user_companies(request.user)
    if not companies.exists():
        return redirect('company_access')
    branches = Branch.objects.filter(company__in=companies)

    if request.method == "POST":
        company_id = request.POST.get("company_id")
        branch_id = request.POST.get("branch_id")

        company = get_object_or_404(Company, id=company_id)
        # التأكد من أن الفرع يتبع للشركة المختارة
        branch = get_object_or_404(Branch, id=branch_id, company=company)

        request.session['company_id'] = company.id
        request.session['company_name'] = company.name

        request.session['branch_id'] = branch.id
        request.session['branch_name'] = branch.name

        return redirect('dashboard')

    return render(request, 'core/select_company_branch.html', {
        "companies": companies.order_by('name'),
        "branches": branches.select_related('company').order_by('company__name', 'name'),
        "title": "اختيار الشركة والفرع"
    }) # _("Select Company and Branch")


@login_required(login_url='login')
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
# ============================
#  Journal PDF
# ============================
def journal_pdf(request, pk):
    entry = get_object_or_404(JournalEntry, pk=pk)
    return render(request, "core/journal_pdf.html", {"entry": entry, "title": "طباعة القيد"})

@login_required(login_url='login')
def account_add(request):
    if request.method == "POST":
        form = AccountForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('accounts_list')  # عدّل الاسم حسب صفحة القائمة
    else:
        form = AccountForm()
    return render(request, 'core/account_form.html', {
        "form": form, "title": "إضافة حساب"
    })
   
