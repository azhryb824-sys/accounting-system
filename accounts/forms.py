from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.models import Permission
from django.db.models import Case, IntegerField, Value, When

from .models import Role, SubscriptionPlan, SubscriptionRequest, UserProfile, UserWarning
from .permission_labels import APP_LABELS, ACTION_LABELS, CODENAME_LABELS, MODEL_LABELS


class NationalIdLoginForm(forms.Form):
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "username"}))
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "current-password"}))


class UserRegistrationForm(forms.ModelForm):
    password = forms.CharField(label="كلمة المرور", widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "أدخل كلمة المرور"}))
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "أدخل رقم الهوية"}))
    phone = forms.CharField(label="رقم الجوال", max_length=15, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "أدخل رقم الجوال"}))

    role = forms.ModelChoiceField(label="الدور", queryset=Role.objects.all(), widget=forms.Select(attrs={"class": "form-select"}))

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


class AdminPermissionMixin:
    def configure_admin_fields(self, can_manage_admins=False):
        permission_queryset = Permission.objects.filter(
            content_type__app_label__in=['auth', 'core', 'accounts', 'invoicing']
        ).select_related('content_type').annotate(
            action_order=Case(
                When(codename__startswith='view_', then=Value(0)),
                When(codename__startswith='add_', then=Value(1)),
                When(codename__startswith='change_', then=Value(2)),
                When(codename__startswith='delete_', then=Value(3)),
                default=Value(9),
                output_field=IntegerField(),
            )
        ).order_by('content_type__app_label', 'content_type__model', 'action_order', 'codename')
        self.fields['user_permissions'].queryset = permission_queryset
        if not can_manage_admins:
            for field_name in ['is_staff', 'is_superuser', 'user_permissions']:
                self.fields.pop(field_name, None)


class AdminUserCreateForm(AdminPermissionMixin, UserCreateForm):
    phone = forms.CharField(label="رقم الجوال", max_length=30, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))

    def __init__(self, *args, can_manage_admins=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.configure_admin_fields(can_manage_admins=can_manage_admins)

    class Meta(UserCreateForm.Meta):
        fields = ["first_name", "last_name", "email", "username", "password", "is_staff", "is_superuser", "user_permissions"]
        labels = {
            **UserCreateForm.Meta.labels,
            "is_staff": "مشرف إدارة",
            "is_superuser": "مشرف كامل الصلاحيات",
            "user_permissions": "صلاحيات الإدارة التفصيلية",
        }
        widgets = {
            **UserCreateForm.Meta.widgets,
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_superuser": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "user_permissions": forms.SelectMultiple(attrs={"class": "form-select", "size": 12}),
        }


class UserEditForm(AdminPermissionMixin, forms.ModelForm):
    national_id = forms.CharField(label="رقم الهوية", max_length=20, widget=forms.TextInput(attrs={"class": "form-control"}))
    phone = forms.CharField(label="رقم الجوال", max_length=30, required=False, widget=forms.TextInput(attrs={"class": "form-control"}))
    role = forms.ModelChoiceField(label="الدور", queryset=Role.objects.all(), required=False, widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, profile=None, can_manage_admins=False, **kwargs):
        super().__init__(*args, **kwargs)
        if profile:
            self.fields["national_id"].initial = profile.national_id
            self.fields["phone"].initial = profile.phone
            self.fields["role"].initial = profile.role
        self.configure_admin_fields(can_manage_admins=can_manage_admins)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "username", "is_active", "is_staff", "is_superuser", "user_permissions"]
        labels = {
            "first_name": "الاسم الأول",
            "last_name": "اسم العائلة",
            "email": "البريد الإلكتروني",
            "username": "اسم المستخدم",
            "is_active": "حساب نشط",
            "is_staff": "مشرف إدارة",
            "is_superuser": "مشرف كامل الصلاحيات",
            "user_permissions": "صلاحيات الإدارة التفصيلية",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_staff": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_superuser": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "user_permissions": forms.SelectMultiple(attrs={"class": "form-select", "size": 12}),
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
        ).order_by('content_type__app_label', 'content_type__model', 'action_order', 'codename')
        labels = {
            "name": "اسم الباقة",
            "role": "الدور المرتبط",
            "price": "السعر الأساسي",
            "monthly_price": "السعر الشهري",
            "yearly_price": "السعر السنوي",
            "duration_days": "مدة الاشتراك بالأيام",
            "trial_days": "أيام التجربة",
            "max_companies": "عدد الشركات المسموح",
            "max_users": "الحد الأقصى للمستخدمين",
            "display_order": "ترتيب العرض",
            "description": "الوصف",
            "features": "المزايا",
            "is_featured": "باقة مميزة",
            "is_active": "نشطة",
        }
        help_texts = {
            "features": "اكتب كل ميزة في سطر مستقل لتظهر بوضوح للعميل.",
            "max_users": "اتركه فارغًا إذا لم يكن هناك حد مستخدمين.",
            "max_companies": "أقصى عدد شركات يمكن للمستخدم إضافتها بهذه الباقة.",
            "price": "يبقى السعر الأساسي للتوافق مع الطلبات الحالية.",
        }
        labels["permissions"] = "صلاحيات الباقة"
        help_texts["permissions"] = "هذه الصلاحيات تمنح للمستخدم بعد قبول طلب الاشتراك."
        for name, label in labels.items():
            self.fields[name].label = label
        for name, help_text in help_texts.items():
            self.fields[name].help_text = help_text
        self.permission_groups = self._build_permission_groups()

    def _build_permission_groups(self):
        selected = set()
        if self.instance and self.instance.pk:
            selected = set(self.instance.permissions.values_list('id', flat=True))
        groups = {}
        for permission in self.fields['permissions'].queryset:
            app_label = permission.content_type.app_label
            model_key = permission.content_type.model
            model_name = MODEL_LABELS.get(model_key, permission.content_type.name)
            action = permission.codename.split('_', 1)[0]
            group_name = APP_LABELS.get(app_label, app_label)
            group = groups.setdefault(group_name, {})
            module = group.setdefault(model_key, {
                "name": model_name,
                "actions": {},
            })
            module["actions"][permission.codename] = {
                "id": permission.id,
                "label": CODENAME_LABELS.get(permission.codename, ACTION_LABELS.get(action, permission.name)),
                "order": ["add", "view", "change", "delete", "close", "reopen", "import"].index(action) if action in ["add", "view", "change", "delete", "close", "reopen", "import"] else 99,
                "checked": permission.id in selected,
            }
        ordered_groups = {}
        for group_name, modules in groups.items():
            ordered_modules = []
            for module in modules.values():
                module["ordered_actions"] = sorted(module["actions"].values(), key=lambda item: (item["order"], item["label"]))
                ordered_modules.append(module)
            ordered_groups[group_name] = sorted(ordered_modules, key=lambda item: item["name"])
        return ordered_groups

    class Meta:
        model = SubscriptionPlan
        fields = [
            "name", "role", "permissions", "price", "monthly_price", "yearly_price",
            "duration_days", "trial_days", "max_companies", "max_users", "display_order",
            "description", "features", "is_featured", "is_active",
        ]
        labels = {"name": "اسم الباقة", "role": "الدور", "price": "السعر", "duration_days": "المدة بالأيام", "description": "الوصف", "is_active": "نشطة"}
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "permissions": forms.SelectMultiple(attrs={"class": "form-select", "size": 12}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "monthly_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "yearly_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "duration_days": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "trial_days": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "max_companies": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "max_users": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "display_order": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "features": forms.Textarea(attrs={"class": "form-control", "rows": 5}),
            "is_featured": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        monthly_price = cleaned_data.get("monthly_price")
        yearly_price = cleaned_data.get("yearly_price")
        trial_days = cleaned_data.get("trial_days") or 0
        duration_days = cleaned_data.get("duration_days") or 0
        if yearly_price and monthly_price and yearly_price > monthly_price * 12:
            self.add_error("yearly_price", "السعر السنوي أعلى من مجموع 12 شهرًا.")
        if trial_days < 1:
            self.add_error("trial_days", "يجب تحديد فترة تجربة لا تقل عن يوم واحد.")
        if duration_days and trial_days > duration_days:
            self.add_error("trial_days", "أيام التجربة لا يمكن أن تتجاوز مدة الاشتراك.")
        return cleaned_data


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
