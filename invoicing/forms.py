from django import forms
from django.forms import inlineformset_factory
from .models import (
    Customer, Invoice, InvoiceItem,
    PurchaseInvoice, PurchaseItem,
    Supplier, Tax, Item
)


# ============================
#  فواتير المبيعات
# ============================
class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['invoice_number', 'invoice_type', 'customer', 'payment_method']
        labels = {
            'invoice_number': 'رقم الفاتورة',
            'invoice_type': 'نوع الفاتورة',
            'customer': 'العميل',
            'payment_method': 'طريقة الدفع',
        }
        widgets = {
            'invoice_number': forms.TextInput(attrs={'class': 'form-control'}),
            'invoice_type': forms.Select(attrs={'class': 'form-select'}),
            'customer': forms.Select(attrs={'class': 'form-select'}),
            'payment_method': forms.Select(
                choices=[('نقدي', 'نقدي'), ('بطاقة', 'بطاقة'), ('تحويل', 'تحويل'), ('آجل', 'آجل')],
                attrs={'class': 'form-select'}
            ),
        }


class InvoiceItemForm(forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ['item', 'description', 'quantity', 'unit_price', 'tax']
        labels = {
            'item': 'الصنف',
            'description': 'الوصف',
            'quantity': 'الكمية',
            'unit_price': 'السعر',
            'tax': 'الضريبة',
        }


InvoiceItemFormSet = inlineformset_factory(
    Invoice,
    InvoiceItem,
    form=InvoiceItemForm,
    extra=1,
    can_delete=True
)


# ============================
#  الضرائب
# ============================
class TaxForm(forms.ModelForm):
    class Meta:
        model = Tax
        fields = ['name', 'rate']


# ============================
#  العملاء
# ============================
class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name', 'vat_number', 'address', 'country']


# ============================
#  الموردين
# ============================
class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name', 'vat_number', 'address', 'country']


# ============================
#  فواتير المشتريات
# ============================
class PurchaseInvoiceForm(forms.ModelForm):
    class Meta:
        model = PurchaseInvoice
        fields = [
            'supplier',
            'invoice_number',
            'issue_date',
            'total_before_vat',
            'vat_amount',
            'total_with_vat'
        ]
        widgets = {
            'issue_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


# ============================
#  الأصناف (المخزون)
# ============================
class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'barcode', 'quantity', 'cost', 'selling_price', 'min_quantity', 'is_active']
        labels = {
            'name': 'اسم المنتج',
            'barcode': 'الباركود',
            'quantity': 'الكمية الافتتاحية',
            'cost': 'التكلفة',
            'selling_price': 'سعر البيع',
            'min_quantity': 'حد التنبيه',
            'is_active': 'متاح للبيع',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control'}),
            'quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cost': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'selling_price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'min_quantity': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AIInvoiceUploadForm(forms.Form):
    invoice_image = forms.FileField(
        label='صورة الفاتورة',
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*,application/pdf'})
    )
