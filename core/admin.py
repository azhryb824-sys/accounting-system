from django.contrib import admin
from .models import Account, Employee, EmployeeAdvance, JournalEntry, JournalEntryLine, MonthlyClose, SalaryRecord


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'type', 'parent', 'level')
    list_filter = ('type',)
    search_fields = ('code', 'name')


class JournalEntryLineInline(admin.TabularInline):
    model = JournalEntryLine
    extra = 1


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'description', 'total_debit', 'total_credit', 'is_balanced')
    list_filter = ('date', 'branch')
    search_fields = ('description',)
    inlines = [JournalEntryLineInline]


@admin.register(JournalEntryLine)
class JournalEntryLineAdmin(admin.ModelAdmin):
    list_display = ('entry', 'account', 'debit', 'credit', 'note')
    list_filter = ('account',)
    search_fields = ('account__name',)


@admin.register(MonthlyClose)
class MonthlyCloseAdmin(admin.ModelAdmin):
    list_display = ('company', 'year', 'month', 'is_closed', 'closed_by', 'closed_at')
    list_filter = ('is_closed', 'year', 'month', 'company')
    search_fields = ('company__name', 'note')


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'branch', 'job_title', 'basic_salary', 'status')
    list_filter = ('company', 'branch', 'status')
    search_fields = ('name', 'national_id', 'phone')


@admin.register(SalaryRecord)
class SalaryRecordAdmin(admin.ModelAdmin):
    list_display = ('employee', 'year', 'month', 'net_salary', 'status')
    list_filter = ('year', 'month', 'status', 'company')
    search_fields = ('employee__name',)


@admin.register(EmployeeAdvance)
class EmployeeAdvanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'amount', 'paid_amount', 'remaining_amount', 'status')
    list_filter = ('status', 'company')
    search_fields = ('employee__name',)
