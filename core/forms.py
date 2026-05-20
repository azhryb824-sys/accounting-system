from django import forms
from django.forms import inlineformset_factory

from accounts.models import Role, SubscriptionPlan
from .models import Account, Branch, Company, CompanyJoinRequest, Employee, EmployeeAdvance, JournalEntry, JournalEntryLine, MonthlyClose, SalaryRecord


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['code', 'name', 'type', 'parent']
        labels = {
            'code': 'الكود',
            'name': 'اسم الحساب',
            'type': 'نوع الحساب',
            'parent': 'الحساب الأب',
        }
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل كود الحساب'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل اسم الحساب'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
        }


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ['name', 'unified_number', 'commercial_number', 'vat_number', 'address']
        labels = {
            'name': 'اسم الشركة',
            'unified_number': 'الرقم الموحد',
            'commercial_number': 'السجل التجاري',
            'vat_number': 'الرقم الضريبي',
            'address': 'العنوان',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل اسم الشركة'}),
            'unified_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل الرقم الموحد'}),
            'commercial_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل رقم السجل التجاري'}),
            'vat_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل الرقم الضريبي'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل العنوان'}),
        }


class CompanySubscriptionRequestForm(CompanyForm):
    requested_role = forms.ModelChoiceField(
        label='دورك داخل الشركة',
        queryset=Role.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text='اتركه فارغًا ليتم تعيينك كمالك الشركة.'
    )


class CompanyJoinRequestForm(forms.Form):
    unified_number = forms.CharField(
        label='الرقم الموحد للشركة',
        max_length=20,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل الرقم الموحد'})
    )
    requested_role = forms.ModelChoiceField(
        label='الدور المطلوب داخل الشركة',
        queryset=Role.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    note = forms.CharField(
        label='ملاحظة',
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'اختياري'})
    )
    plan = forms.ModelChoiceField(
        label='باقة الاشتراك',
        queryset=SubscriptionPlan.objects.filter(is_active=True).order_by('display_order', 'price', 'name'),
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    bank_name = forms.CharField(
        label='البنك المحول منه',
        max_length=120,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    transfer_reference = forms.CharField(
        label='رقم عملية التحويل',
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    transfer_notice = forms.FileField(
        label='إيصال التحويل',
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = ['company', 'name', 'code', 'address', 'is_active']
        labels = {
            'company': 'الشركة',
            'name': 'اسم الفرع',
            'code': 'كود الفرع',
            'address': 'العنوان',
            'is_active': 'نشط',
        }
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل اسم الفرع'}),
            'code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل كود الفرع'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل العنوان'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class JournalEntryForm(forms.ModelForm):
    class Meta:
        model = JournalEntry
        fields = ['date', 'description']
        labels = {
            'date': 'التاريخ',
            'description': 'الوصف',
        }
        widgets = {
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'أدخل وصف القيد'}),
        }


class MonthlyCloseForm(forms.ModelForm):
    class Meta:
        model = MonthlyClose
        fields = ['company', 'year', 'month', 'note']
        labels = {
            'company': 'الشركة',
            'year': 'السنة',
            'month': 'الشهر',
            'note': 'ملاحظة',
        }
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100}),
            'month': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 12}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'اختياري'}),
        }

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields['company'].queryset = companies

    def clean_month(self):
        month = self.cleaned_data['month']
        if month < 1 or month > 12:
            raise forms.ValidationError("الشهر يجب أن يكون بين 1 و 12.")
        return month


JournalEntryLineFormSet = inlineformset_factory(
    JournalEntry,
    JournalEntryLine,
    fields=('account', 'debit', 'credit', 'note'),
    extra=2,
    widgets={
        'account': forms.Select(attrs={'class': 'form-select'}),
        'debit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        'credit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        'note': forms.TextInput(attrs={'class': 'form-control'}),
    }
)


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            'company', 'branch', 'name', 'national_id', 'job_title', 'phone', 'hire_date',
            'basic_salary', 'housing_allowance', 'transport_allowance', 'other_allowances',
            'status', 'notes',
        ]
        labels = {
            'company': 'الشركة',
            'branch': 'الفرع',
            'name': 'اسم الموظف',
            'national_id': 'رقم الهوية',
            'job_title': 'المسمى الوظيفي',
            'phone': 'الجوال',
            'hire_date': 'تاريخ التعيين',
            'basic_salary': 'الراتب الأساسي',
            'housing_allowance': 'بدل السكن',
            'transport_allowance': 'بدل النقل',
            'other_allowances': 'بدلات أخرى',
            'status': 'الحالة',
            'notes': 'ملاحظات',
        }
        widgets = {
            'company': forms.Select(attrs={'class': 'form-select'}),
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'national_id': forms.TextInput(attrs={'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'hire_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'basic_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'housing_allowance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'transport_allowance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'other_allowances': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields['company'].queryset = companies
            self.fields['branch'].queryset = Branch.objects.filter(company__in=companies)


class SalaryRecordForm(forms.ModelForm):
    class Meta:
        model = SalaryRecord
        fields = ['employee', 'year', 'month', 'basic_salary', 'allowances', 'deductions', 'advances_deduction', 'status', 'payment_date', 'note']
        labels = {
            'employee': 'الموظف',
            'year': 'السنة',
            'month': 'الشهر',
            'basic_salary': 'الراتب الأساسي',
            'allowances': 'البدلات',
            'deductions': 'الخصومات',
            'advances_deduction': 'خصم السلف',
            'status': 'الحالة',
            'payment_date': 'تاريخ الدفع',
            'note': 'ملاحظة',
        }
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'year': forms.NumberInput(attrs={'class': 'form-control', 'min': 2000, 'max': 2100}),
            'month': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 12}),
            'basic_salary': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'allowances': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'deductions': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'advances_deduction': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'payment_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields['employee'].queryset = Employee.objects.filter(company__in=companies, status='active')


class EmployeeAdvanceForm(forms.ModelForm):
    class Meta:
        model = EmployeeAdvance
        fields = ['employee', 'date', 'amount', 'paid_amount', 'status', 'note']
        labels = {
            'employee': 'الموظف',
            'date': 'التاريخ',
            'amount': 'مبلغ السلفة',
            'paid_amount': 'المبلغ المسدد',
            'status': 'الحالة',
            'note': 'ملاحظة',
        }
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'paid_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields['employee'].queryset = Employee.objects.filter(company__in=companies, status='active')
