from django.db import models


class Account(models.Model):
    ACCOUNT_TYPES = [
        ('asset', 'أصل'),
        ('liability', 'التزام'),
        ('equity', 'حقوق ملكية'),
        ('revenue', 'إيراد'),
        ('expense', 'مصروف'),
    ]

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    level = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.code} - {self.name}"


class Company(models.Model):
    SUBSCRIPTION_STATUS_CHOICES = [
        ('pending', 'بانتظار الموافقة'),
        ('active', 'نشطة'),
        ('rejected', 'مرفوضة'),
    ]

    owner = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='owned_companies')
    owner_role = models.ForeignKey('accounts.Role', null=True, blank=True, on_delete=models.SET_NULL, related_name='owned_companies')
    active_plan = models.ForeignKey('accounts.SubscriptionPlan', null=True, blank=True, on_delete=models.SET_NULL, related_name='active_companies')
    name = models.CharField(max_length=255)
    unified_number = models.CharField(max_length=20, unique=True)
    commercial_number = models.CharField(max_length=50, blank=True, null=True)
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS_CHOICES, default='pending')
    subscription_starts_at = models.DateTimeField(null=True, blank=True)
    subscription_ends_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)

    def has_active_subscription(self):
        from django.utils import timezone

        now = timezone.now()
        if self.subscription_status != 'active':
            return False
        if self.subscription_ends_at and self.subscription_ends_at >= now:
            return True
        if self.trial_ends_at and self.trial_ends_at >= now:
            return True
        return False

    def __str__(self):
        return f"{self.name} ({self.unified_number})"


class Branch(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.company.name} - {self.name}"


class CompanyMembership(models.Model):
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='company_memberships')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='memberships')
    role = models.ForeignKey('accounts.Role', null=True, blank=True, on_delete=models.SET_NULL, related_name='company_memberships')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'company')

    def __str__(self):
        return f"{self.user} - {self.company}"


class CompanyJoinRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'بانتظار الموافقة'),
        ('approved', 'مقبول'),
        ('rejected', 'مرفوض'),
    ]

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='company_join_requests')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='join_requests')
    requested_role = models.ForeignKey('accounts.Role', null=True, blank=True, on_delete=models.SET_NULL, related_name='company_join_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_company_join_requests')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'company', 'status')

    def __str__(self):
        return f"{self.user} -> {self.company} ({self.status})"


class JournalEntry(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    date = models.DateField()
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def total_debit(self):
        return self.lines.aggregate(total=models.Sum('debit'))['total'] or 0

    def total_credit(self):
        return self.lines.aggregate(total=models.Sum('credit'))['total'] or 0

    def is_balanced(self):
        return self.total_debit() == self.total_credit()

    def __str__(self):
        return f"قيد #{self.id} بتاريخ {self.date}"


class JournalEntryLine(models.Model):
    entry = models.ForeignKey(JournalEntry, related_name='lines', on_delete=models.CASCADE)
    account = models.ForeignKey(Account, on_delete=models.PROTECT)
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    note = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.account.name} | مدين: {self.debit} | دائن: {self.credit}"


class MonthlyClose(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='monthly_closes')
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    is_closed = models.BooleanField(default=True)
    closed_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='closed_months')
    reopened_by = models.ForeignKey('auth.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='reopened_months')
    note = models.TextField(blank=True)
    closed_at = models.DateTimeField(auto_now_add=True)
    reopened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('company', 'year', 'month')
        ordering = ['-year', '-month']
        permissions = [
            ('close_month', 'يمكنه قفل شهر محاسبي'),
            ('reopen_month', 'يمكنه إعادة فتح شهر محاسبي'),
        ]

    @property
    def period_label(self):
        return f"{self.year}-{self.month:02d}"

    def __str__(self):
        status = "مقفل" if self.is_closed else "مفتوح"
        return f"{self.company.name} - {self.period_label} ({status})"


class Employee(models.Model):
    STATUS_CHOICES = [('active', 'نشط'), ('inactive', 'غير نشط')]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='employees')
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name='employees')
    name = models.CharField(max_length=180)
    national_id = models.CharField(max_length=30, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transport_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    other_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    @property
    def gross_salary(self):
        return self.basic_salary + self.housing_allowance + self.transport_allowance + self.other_allowances

    def __str__(self):
        return self.name


class SalaryRecord(models.Model):
    STATUS_CHOICES = [('draft', 'مسودة'), ('approved', 'معتمد'), ('paid', 'مدفوع')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='salary_records')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='salary_records')
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name='salary_records')
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    advances_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    payment_date = models.DateField(null=True, blank=True)
    accrual_entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='salary_accrual_records',
    )
    payment_entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='salary_payment_records',
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'year', 'month')
        ordering = ['-year', '-month', 'employee__name']

    @property
    def period_label(self):
        return f"{self.year}-{self.month:02d}"

    def save(self, *args, **kwargs):
        self.company = self.employee.company
        self.branch = self.employee.branch
        self.net_salary = self.basic_salary + self.allowances - self.deductions - self.advances_deduction
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.name} - {self.period_label}"


class EmployeeAdvance(models.Model):
    STATUS_CHOICES = [('open', 'قائمة'), ('settled', 'مسددة'), ('cancelled', 'ملغاة')]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='advances')
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='employee_advances')
    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name='employee_advances')
    date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    journal_entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='employee_advances',
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-id']

    @property
    def remaining_amount(self):
        return self.amount - self.paid_amount

    def save(self, *args, **kwargs):
        self.company = self.employee.company
        self.branch = self.employee.branch
        if self.paid_amount >= self.amount and self.status != 'cancelled':
            self.status = 'settled'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.name} - {self.amount}"
