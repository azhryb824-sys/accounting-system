from decimal import Decimal

from core.models import Account, JournalEntry, JournalEntryLine


DEFAULT_ACCOUNTS = {
    "1000": ("الصندوق / البنك", "asset"),
    "1101": ("العملاء", "asset"),
    "1200": ("المخزون", "asset"),
    "1300": ("سلف الموظفين", "asset"),
    "2100": ("ضريبة القيمة المضافة", "liability"),
    "2200": ("الموردون", "liability"),
    "2300": ("رواتب مستحقة", "liability"),
    "4100": ("إيرادات المبيعات", "revenue"),
    "5100": ("تكلفة البضاعة المباعة", "expense"),
    "5200": ("مصروف الرواتب", "expense"),
}


def account(code):
    name, account_type = DEFAULT_ACCOUNTS[code]
    obj, _ = Account.objects.get_or_create(
        code=code,
        defaults={"name": name, "type": account_type, "level": 1},
    )
    return obj


def create_balanced_entry(branch, date, description, lines):
    entry = JournalEntry.objects.create(branch=branch, date=date, description=description)
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for line in lines:
        debit = Decimal(line.get("debit") or 0)
        credit = Decimal(line.get("credit") or 0)
        total_debit += debit
        total_credit += credit
        JournalEntryLine.objects.create(
            entry=entry,
            account=account(line["account"]),
            debit=debit,
            credit=credit,
            note=line.get("note", ""),
        )
    if total_debit != total_credit:
        raise ValueError(f"القيد غير متوازن: مدين {total_debit} / دائن {total_credit}")
    return entry
