from django.contrib import admin

from .models import Expense, FilingProfile, IncomeStatement, ManualJournalEntry, OpeningBalance, OtherIncome, Receipt, TaxSettings


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ["id", "stylist", "status", "created_at"]
    list_filter = ["status"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["date", "stylist", "category", "amount", "business_ratio", "payment_method", "status"]
    list_filter = ["category", "payment_method", "status"]


@admin.register(IncomeStatement)
class IncomeStatementAdmin(admin.ModelAdmin):
    list_display = ["stylist", "year", "month", "salon_name", "commission_amount", "net_paid", "status"]
    list_filter = ["status", "year"]


@admin.register(OtherIncome)
class OtherIncomeAdmin(admin.ModelAdmin):
    list_display = ["date", "stylist", "description", "amount"]


@admin.register(OpeningBalance)
class OpeningBalanceAdmin(admin.ModelAdmin):
    list_display = ["stylist", "year", "cash", "bank", "receivable"]


@admin.register(ManualJournalEntry)
class ManualJournalEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "stylist", "debit_account", "credit_account", "amount"]


@admin.register(TaxSettings)
class TaxSettingsAdmin(admin.ModelAdmin):
    list_display = ["stylist", "blue_deduction", "pension_monthly", "nhi_rate_pct"]


@admin.register(FilingProfile)
class FilingProfileAdmin(admin.ModelAdmin):
    list_display = ["stylist", "full_name", "opened_on", "bookkeeping", "uses_etax"]
