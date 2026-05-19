from django import forms
from django.forms import inlineformset_factory
from .models import Account, Company, Branch, JournalEntry, JournalEntryLine

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


# ============================
#  نموذج الشركة
# ============================
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


# ============================
#  نموذج الفرع
# ============================
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


# ============================
#  نموذج رأس القيد
# ============================
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