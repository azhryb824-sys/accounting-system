from core.models import Account, JournalEntryLine
from django.db.models import Sum

class TrialBalanceService:

    @staticmethod
    def generate():
        """
        إنشاء ميزان المراجعة لجميع الحسابات
        """
        accounts = Account.objects.all()
        report = []

        for acc in accounts:
            totals = JournalEntryLine.objects.filter(account=acc).aggregate(
                debit=Sum('debit'),
                credit=Sum('credit')
            )

            debit = totals['debit'] or 0
            credit = totals['credit'] or 0
            balance = debit - credit

            report.append({
                "code": acc.code,
                "name": acc.name,
                "debit": float(debit),
                "credit": float(credit),
                "balance": float(balance)
            })

        return report
