from django.contrib import admin
from .models import Account, JournalEntry, JournalEntryLine


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
