from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from core.models import Branch, EmployeeAdvance
from core.services.accounting import create_balanced_entry
from core.services.monthly_close import assert_month_open


def _salary_branch(salary):
    return salary.branch or Branch.objects.filter(company=salary.company).first()


def _apply_advance_deduction(salary):
    remaining = Decimal(salary.advances_deduction or 0)
    if remaining <= 0:
        return Decimal("0.00")

    open_advances = EmployeeAdvance.objects.select_for_update().filter(
        employee=salary.employee,
        status='open',
    ).order_by('date', 'id')
    applied = Decimal("0.00")
    for advance in open_advances:
        if remaining <= 0:
            break
        amount = min(advance.remaining_amount, remaining)
        advance.paid_amount += amount
        advance.save(update_fields=['paid_amount', 'status'])
        remaining -= amount
        applied += amount
    return applied


@transaction.atomic
def approve_salary(salary, date_value=None):
    if salary.accrual_entry_id:
        return salary.accrual_entry

    salary = salary.__class__.objects.select_for_update().select_related('employee', 'company', 'branch').get(id=salary.id)
    if salary.accrual_entry_id:
        return salary.accrual_entry

    date_value = date_value or salary.payment_date or timezone.localdate()
    assert_month_open(salary.company, date_value)
    gross_salary = Decimal(salary.basic_salary or 0) + Decimal(salary.allowances or 0) - Decimal(salary.deductions or 0)
    advance_deduction = Decimal(salary.advances_deduction or 0)
    if advance_deduction > 0:
        applied = _apply_advance_deduction(salary)
        if applied != advance_deduction:
            raise ValueError("خصم السلف أكبر من الرصيد المفتوح للموظف.")

    lines = [
        {"account": "5200", "debit": gross_salary, "note": "استحقاق راتب"},
    ]
    if advance_deduction > 0:
        lines.append({"account": "1300", "credit": advance_deduction, "note": "خصم سلفة من الراتب"})
    lines.append({"account": "2300", "credit": salary.net_salary, "note": "رواتب مستحقة"})

    entry = create_balanced_entry(
        branch=_salary_branch(salary),
        date=date_value,
        description=f"استحقاق راتب {salary.employee.name} عن {salary.period_label}",
        lines=lines,
    )
    salary.status = 'approved'
    salary.accrual_entry = entry
    salary.save(update_fields=['status', 'accrual_entry'])
    return entry


@transaction.atomic
def pay_salary(salary, date_value=None):
    salary = salary.__class__.objects.select_for_update().select_related('employee', 'company', 'branch').get(id=salary.id)
    if salary.payment_entry_id:
        return salary.payment_entry
    if not salary.accrual_entry_id:
        approve_salary(salary, date_value=date_value)
        salary.refresh_from_db()

    date_value = date_value or salary.payment_date or timezone.localdate()
    assert_month_open(salary.company, date_value)
    entry = create_balanced_entry(
        branch=_salary_branch(salary),
        date=date_value,
        description=f"صرف راتب {salary.employee.name} عن {salary.period_label}",
        lines=[
            {"account": "2300", "debit": salary.net_salary, "note": "سداد راتب مستحق"},
            {"account": "1000", "credit": salary.net_salary, "note": "صرف راتب"},
        ],
    )
    salary.status = 'paid'
    salary.payment_date = date_value
    salary.payment_entry = entry
    salary.save(update_fields=['status', 'payment_date', 'payment_entry'])
    return entry
