from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.models import Permission
from django.db.models import Case, IntegerField, Value, When

from .models import Role, SubscriptionPlan, SubscriptionRequest, UserProfile, UserWarning


class NationalIdLoginForm(forms.Form):
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}))
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "current-password"}))


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "أدخل كلمة المرور"}))
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "أدخل رقم الهوية"}))
    phone = forms.CharField(label="رقم الجوال", max_length=15, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "أدخل رقم الجوال"}))

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "username"]
        labels = {
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "email": "البريد الإلكتروني",
            "username": "اسم المستخدم",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "الاسم الأول"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "اسم العائلة"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "example@domain.com"}),
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "اختر اسم مستخدم"}),
        }


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "form-control"}))
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control"}))
    role = forms.ModelChoiceField(label="الدور", queryset=Role.objects.all(), required=False, widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "username", "password"]
        labels = {"first_name": "الاسم الأول", "last_name": "اسم العائلة", "email": "البريد الإلكتروني", "username": "اسم المستخدم"}
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "username": forms.TextInput(attrs={"class": "form-control"}),
        }


class RoleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # تصفية الصلاحيات لتسهيل الاختيار (عرض الصلاحيات المتعلقة بالنظام فقط)
        self.fields['permissions'].queryset = Permission.objects.filter(
            content_type__app_label__in=['core', 'accounts', 'invoicing']
        ).select_related('content_type').annotate(
            action_order=Case(
                When(codename__startswith='view_', then=Value(0)),
                When(codename__startswith='add_', then=Value(1)),
                When(codename__startswith='change_', then=Value(2)),
                When(codename__startswith='delete_', then=Value(3)),
                default=Value(9),
                output_field=IntegerField(),
            )
        ).order_by(
            'content_type__app_label',
            'content_type__model',
            'action_order',
            'codename',
        )

    class Meta:
        model = Role
        fields = ["name", "description", "requires_subscription", "permissions"]
        labels = {"name": "اسم الدور", "description": "الوصف", "requires_subscription": "يتطلب اشتراك", "permissions": "الصلاحيات"}
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "requires_subscription": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SubscriptionPlanForm(forms.ModelForm):
    class Meta:
        model = SubscriptionPlan
        fields = ["name", "role", "price", "duration_days", "description", "is_active"]
        labels = {"name": "اسم الباقة", "role": "الدور", "price": "السعر", "duration_days": "المدة بالأيام", "description": "الوصف", "is_active": "نشطة"}
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "duration_days": forms.NumberInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SubscriptionRequestForm(forms.ModelForm):
    class Meta:
        model = SubscriptionRequest
        fields = ["plan", "bank_name", "transfer_reference", "transfer_notice"]
        labels = {"plan": "الباقة", "bank_name": "البنك المحول منه", "transfer_reference": "رقم العملية", "transfer_notice": "إشعار التحويل"}
        widgets = {
            "plan": forms.Select(attrs={"class": "form-select"}),
            "bank_name": forms.TextInput(attrs={"class": "form-control"}),
            "transfer_reference": forms.TextInput(attrs={"class": "form-control"}),
            "transfer_notice": forms.FileInput(attrs={"class": "form-control"}),
        }


class WarningForm(forms.ModelForm):
    class Meta:
        model = UserWarning
        fields = ["title", "message"]
        labels = {"title": "عنوان الإنذار", "message": "نص الإنذار"}
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "message": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }


class DisableUserForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ["is_disabled_by_admin", "disabled_reason"]
        labels = {"is_disabled_by_admin": "تعطيل الحساب", "disabled_reason": "سبب التعطيل"}
        widgets = {
            "is_disabled_by_admin": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "disabled_reason": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
