from core.models import Account
from core.services.trial_balance import TrialBalanceService

class FinancialReports:

    @staticmethod
    def income_statement():
        """
        قائمة الدخل: الإيرادات - المصروفات
        """
        tb = TrialBalanceService.generate()

        revenue = sum(item["balance"] for item in tb if "إيراد" in item["name"] or item["balance"] < 0)
        expenses = sum(item["balance"] for item in tb if "مصروف" in item["name"] or item["balance"] > 0)

        net_income = revenue - expenses

        return {
            "revenue": revenue,
            "expenses": expenses,
            "net_income": net_income
        }

    @staticmethod
    def balance_sheet():
        """
        الميزانية العمومية: الأصول – الالتزامات – حقوق الملكية
        """
        tb = TrialBalanceService.generate()

        assets = sum(item["balance"] for item in tb if "أصل" in item["name"])
        liabilities = sum(item["balance"] for item in tb if "التزام" in item["name"])
        equity = sum(item["balance"] for item in tb if "حقوق" in item["name"])

        return {
            "assets": assets,
            "liabilities": liabilities,
            "equity": equity,
            "equation_valid": assets == liabilities + equity
        }
