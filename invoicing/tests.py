from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import Branch, Company
from invoicing.models import Customer, Invoice, InvoiceItem, Item, PurchaseInvoice, PurchaseItem, Supplier, Tax
from invoicing.purchase_views import post_purchase_invoice
from invoicing.views import post_sales_invoice


class InvoiceAccountingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Co", unified_number="200")
        self.branch = Branch.objects.create(company=self.company, name="Main")
        self.tax = Tax.objects.create(name="VAT", rate=Decimal("15.00"))
        self.item = Item.objects.create(
            branch=self.branch,
            name="Item",
            quantity=Decimal("10.00"),
            cost=Decimal("20.00"),
            selling_price=Decimal("50.00"),
        )

    def test_sales_invoice_posts_once_and_reduces_inventory_once(self):
        customer = Customer.objects.create(name="Customer")
        invoice = Invoice.objects.create(
            branch=self.branch,
            invoice_number="S-1",
            invoice_type="standard",
            customer=customer,
            total_amount=Decimal("100.00"),
            total_vat=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
            payment_method="نقدي",
        )
        InvoiceItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            description="Item",
            quantity=Decimal("2.00"),
            unit_price=Decimal("50.00"),
            tax=self.tax,
            line_total=Decimal("100.00"),
            line_vat=Decimal("15.00"),
            line_total_with_vat=Decimal("115.00"),
        )

        first = post_sales_invoice(invoice)
        self.item.refresh_from_db()
        invoice.refresh_from_db()
        second = post_sales_invoice(invoice)

        self.assertEqual(first.id, second.id)
        self.assertEqual(invoice.journal_entry_id, first.id)
        self.assertEqual(self.item.quantity, Decimal("8.00"))
        self.assertEqual(first.total_debit(), first.total_credit())

    def test_purchase_item_creation_does_not_auto_double_inventory(self):
        supplier = Supplier.objects.create(name="Supplier")
        invoice = PurchaseInvoice.objects.create(
            branch=self.branch,
            supplier=supplier,
            invoice_number="P-1",
            issue_date=timezone.localdate(),
            total_before_vat=Decimal("100.00"),
            vat_amount=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
        )

        PurchaseItem.objects.create(
            branch=self.branch,
            invoice=invoice,
            item=self.item,
            quantity=Decimal("3.00"),
            price=Decimal("25.00"),
        )
        self.item.refresh_from_db()

        self.assertEqual(self.item.quantity, Decimal("10.00"))

    def test_purchase_invoice_links_balanced_entry_once(self):
        supplier = Supplier.objects.create(name="Supplier")
        invoice = PurchaseInvoice.objects.create(
            branch=self.branch,
            supplier=supplier,
            invoice_number="P-2",
            issue_date=timezone.localdate(),
            total_before_vat=Decimal("100.00"),
            vat_amount=Decimal("15.00"),
            total_with_vat=Decimal("115.00"),
        )

        first = post_purchase_invoice(invoice)
        invoice.refresh_from_db()
        second = post_purchase_invoice(invoice)

        self.assertEqual(first.id, second.id)
        self.assertEqual(invoice.journal_entry_id, first.id)
        self.assertEqual(first.total_debit(), first.total_credit())
