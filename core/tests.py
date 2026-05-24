from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from core.forms import CompanySubscriptionRequestForm
from core.models import Branch, Company, Employee, EmployeeAdvance, SalaryRecord
from core.services.payroll import approve_salary, pay_salary


class PayrollAccountingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Co", unified_number="100")
        self.branch = Branch.objects.create(company=self.company, name="Main")
        self.employee = Employee.objects.create(
            company=self.company,
            branch=self.branch,
            name="Employee",
            basic_salary=Decimal("1000.00"),
        )

    def test_salary_approval_creates_accrual_only(self):
        salary = SalaryRecord.objects.create(
            employee=self.employee,
            year=2026,
            month=5,
            basic_salary=Decimal("1000.00"),
            allowances=Decimal("200.00"),
            deductions=Decimal("50.00"),
            status="draft",
        )

        entry = approve_salary(salary, timezone.localdate())
        salary.refresh_from_db()

        self.assertEqual(salary.status, "approved")
        self.assertEqual(salary.accrual_entry_id, entry.id)
        self.assertIsNone(salary.payment_entry_id)
        self.assertEqual(entry.total_debit(), entry.total_credit())

    def test_salary_payment_creates_payment_entry_once(self):
        salary = SalaryRecord.objects.create(
            employee=self.employee,
            year=2026,
            month=5,
            basic_salary=Decimal("1000.00"),
            status="approved",
        )

        first = pay_salary(salary, timezone.localdate())
        salary.refresh_from_db()
        second = pay_salary(salary, timezone.localdate())

        self.assertEqual(first.id, second.id)
        self.assertEqual(salary.status, "paid")
        self.assertEqual(salary.payment_entry_id, first.id)

    def test_salary_advance_deduction_updates_advance(self):
        advance = EmployeeAdvance.objects.create(
            employee=self.employee,
            date=timezone.localdate(),
            amount=Decimal("300.00"),
        )
        salary = SalaryRecord.objects.create(
            employee=self.employee,
            year=2026,
            month=5,
            basic_salary=Decimal("1000.00"),
            advances_deduction=Decimal("300.00"),
            status="draft",
        )

        approve_salary(salary, timezone.localdate())
        advance.refresh_from_db()

        self.assertEqual(advance.paid_amount, Decimal("300.00"))
        self.assertEqual(advance.status, "settled")


class CompanyFormMobileTests(TestCase):
    def test_company_attachment_input_is_mobile_friendly(self):
        form = CompanySubscriptionRequestForm()
        widget = form.fields["transfer_notice"].widget
        template = Path("core/templates/core/company_form.html").read_text(encoding="utf-8")

        self.assertIn("mobile-file-input", widget.attrs["class"])
        self.assertEqual(widget.attrs["accept"], "image/*,.pdf")
        self.assertIn("data-file-picker", template)
        self.assertIn("إرفاق إيصال التحويل", template)
        self.assertIn("input.click()", template)
