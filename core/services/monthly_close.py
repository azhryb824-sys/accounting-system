from django.core.exceptions import PermissionDenied

from core.models import MonthlyClose


def is_month_closed(company, date_value):
    if not company or not date_value:
        return False
    return MonthlyClose.objects.filter(
        company=company,
        year=date_value.year,
        month=date_value.month,
        is_closed=True,
    ).exists()


def assert_month_open(company, date_value):
    if is_month_closed(company, date_value):
        raise PermissionDenied("هذا الشهر مقفل محاسبياً ولا يمكن إضافة أو تعديل عمليات داخله.")
