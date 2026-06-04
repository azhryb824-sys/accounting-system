from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import CompanySubscriptionRequestForm
from core.models import Branch, Company, Employee, EmployeeAdvance, SalaryRecord
from accounts.models import UserProfile
from core.services.payroll import approve_salary, pay_salary

User = get_user_model()


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


class DashboardAccessTests(TestCase):
    def test_superuser_can_open_dashboard_without_company_or_branch(self):
        user = User.objects.create_superuser(username="admin", password="pass")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["admin_mode_without_scope"])
        self.assertContains(response, "وضع المشرف الرئيسي")

    def test_primary_admin_can_open_dashboard_without_company_or_branch(self):
        user = User.objects.create_user(username="primary", password="pass")
        UserProfile.objects.create(user=user, national_id="2572280689")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["admin_mode_without_scope"])

    def test_regular_user_without_company_still_goes_to_company_access(self):
        user = User.objects.create_user(username="regular", password="pass")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("company_access"))

    def test_dashboard_with_selected_branch_does_not_filter_accounts_by_company(self):
        user = User.objects.create_superuser(username="scoped-admin", password="pass")
        company = Company.objects.create(name="Scoped Co", unified_number="300")
        branch = Branch.objects.create(company=company, name="Main")
        session = self.client.session
        session["company_id"] = company.id
        session["company_name"] = company.name
        session["branch_id"] = branch.id
        session["branch_name"] = branch.name
        session.save()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["accounts_count"], 0)


class CompanyBranchButtonsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="pass")
        self.company = Company.objects.create(
            owner=self.user,
            name="Owner Co",
            unified_number="200",
            subscription_status="active",
            subscription_ends_at=timezone.now() + timezone.timedelta(days=30),
        )
        self.branch = Branch.objects.create(company=self.company, name="Main")

    def test_company_list_shows_branch_actions_for_company_owner(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("company_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("branch_list") + f"?company={self.company.id}")
        self.assertContains(response, reverse("branch_add") + f"?company={self.company.id}")
        self.assertContains(response, "إضافة فرع")

    def test_branch_list_can_filter_by_company_from_company_list_button(self):
        other = Company.objects.create(name="Other Co", unified_number="201")
        Branch.objects.create(company=other, name="Hidden")
        self.client.force_login(self.user)
        session = self.client.session
        session["company_id"] = self.company.id
        session["branch_id"] = self.branch.id
        session.save()

        response = self.client.get(reverse("branch_list"), {"company": self.company.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Owner Co")
        self.assertContains(response, "Main")
        self.assertNotContains(response, "Hidden")
