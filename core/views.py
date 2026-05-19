from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout, login
from .models import Account, JournalEntry, Company, Branch, JournalEntryLine
from .forms import CompanyForm, BranchForm, JournalEntryForm, JournalEntryLineFormSet, AccountForm
from accounts.forms import UserRegistrationForm
from accounts.models import UserProfile
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
        return redirect('select_company_branch')

    context = {
        "accounts_count": Account.objects.count(),
        "entries_count": JournalEntry.objects.filter(branch_id=branch_id).count(),
        "branch_name": request.session.get("branch_name"),
        "company_name": request.session.get("company_name"),
        "title": "لوحة التحكم",
    }
    return render(request, 'core/dashboard.html', context)

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
            )

            login(request, user)
            return redirect('select_company_branch')
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
            form.save()
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
        form = CompanyForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('company_list')
    else:
        form = CompanyForm()

    return render(request, 'core/company_form.html', {
        "form": form, "title": "إضافة شركة"
    })

@login_required(login_url='login')
def company_list(request):
    companies = Company.objects.all()
    return render(request, 'core/company_list.html', {"companies": companies, "title": "الشركات"})



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
    companies = Company.objects.all()
    branches = Branch.objects.all()

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
   