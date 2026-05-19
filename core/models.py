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
    name = models.CharField(max_length=255)
    unified_number = models.CharField(max_length=20, unique=True)
    commercial_number = models.CharField(max_length=50, blank=True, null=True)
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)

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
