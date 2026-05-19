from core.models import JournalEntryLine

class LedgerService:

    @staticmethod
    def get_account_ledger(account_id):
        """
        إرجاع دفتر الأستاذ لحساب معيّن
        """
        lines = JournalEntryLine.objects.filter(account_id=account_id).order_by('entry__date', 'id')

        ledger = []
        balance = 0

        for line in lines:
            balance += float(line.debit) - float(line.credit)

            ledger.append({
                "date": line.entry.date,
                "description": line.entry.description,
                "debit": float(line.debit),
                "credit": float(line.credit),
                "balance": balance
            })

        return ledger
