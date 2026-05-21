from django.db import models
import uuid
from core.models import Branch, JournalEntry


# ============================
#  العملاء
# ============================
class Customer(models.Model):
    name = models.CharField(max_length=200)
    vat_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.CharField(max_length=300, blank=True, null=True)
    country = models.CharField(max_length=50, default="SA")

    def __str__(self):
        return self.name


# ============================
#  الضرائب
# ============================
class Tax(models.Model):
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2)

    def __str__(self):
        return f"{self.name} ({self.rate}%)"


# ============================
#  فواتير المبيعات
# ============================
class Invoice(models.Model):
    INVOICE_TYPES = [
        ('standard', 'فاتورة ضريبية'),
        ('simplified', 'فاتورة مبسطة'),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_type = models.CharField(max_length=20, choices=INVOICE_TYPES)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    issue_date = models.DateTimeField(auto_now_add=True)

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_with_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    is_posted = models.BooleanField(default=False)
    journal_entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='sales_invoices',
    )
    zatca_qr = models.TextField(blank=True, default="")
    zatca_xml = models.TextField(blank=True, default="")
    zatca_hash = models.CharField(max_length=128, blank=True, default="")
    zatca_status = models.CharField(max_length=30, default="مسودة")
    zatca_warnings = models.TextField(blank=True, default="")
    payment_method = models.CharField(max_length=30, default="نقدي")

    def __str__(self):
        return f"فاتورة {self.invoice_number}"


class InvoiceItem(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    invoice = models.ForeignKey(Invoice, related_name='items', on_delete=models.CASCADE)
    item = models.ForeignKey("Item", on_delete=models.PROTECT)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    tax = models.ForeignKey(Tax, on_delete=models.PROTECT)

    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total_with_vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return self.description


# ============================
#  الموردين
# ============================
class Supplier(models.Model):
    name = models.CharField(max_length=255)
    vat_number = models.CharField(max_length=50, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name


# ============================
#  فواتير المشتريات
# ============================
class PurchaseInvoice(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_invoices')
    invoice_number = models.CharField(max_length=50)
    issue_date = models.DateField()

    total_before_vat = models.DecimalField(max_digits=10, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_with_vat = models.DecimalField(max_digits=10, decimal_places=2)
    journal_entry = models.ForeignKey(
        JournalEntry,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='purchase_invoices',
    )

    class Meta:
        permissions = [
            ("import_ai_invoice", "إضافة فاتورة بالذكاء الاصطناعي"),
            ("view_ai_insights", "عرض نصائح وتوقعات الذكاء الاصطناعي"),
        ]

    def __str__(self):
        return f"فاتورة شراء {self.invoice_number} - {self.supplier.name}"


# ============================
#  الأصناف (المخزون)
# ============================
class Item(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    barcode = models.CharField(max_length=80, blank=True, null=True, db_index=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


# ============================
#  تفاصيل فاتورة المشتريات
# ============================
class PurchaseItem(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.item.name} - {self.quantity}"


# ============================
#  حركة المخزون
# ============================
class StockMovement(models.Model):
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    movement_type = models.CharField(max_length=10)  # IN / OUT
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item.name} - {self.movement_type} - {self.quantity}"
