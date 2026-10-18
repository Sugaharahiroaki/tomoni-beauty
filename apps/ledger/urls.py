from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("receipts/", views.receipts, name="receipts"),
    path("receipts/upload/", views.receipt_upload, name="receipt_upload"),
    path("receipts/<int:pk>/", views.receipt_review, name="receipt_review"),
    path("receipts/<int:pk>/status.json", views.receipt_status, name="receipt_status"),
    path("receipts/<int:pk>/delete/", views.receipt_delete, name="receipt_delete"),
    path("receipts/<int:pk>/retry/", views.receipt_retry, name="receipt_retry"),
    path("expenses/", views.expenses, name="expenses"),
    path("expenses/new/", views.expense_create, name="expense_create"),
    path("expenses/<int:pk>/edit/", views.expense_edit, name="expense_edit"),
    path("expenses/<int:pk>/delete/", views.expense_delete, name="expense_delete"),
    path("expenses/export.csv", views.expenses_csv, name="expenses_csv"),
    path("statements/", views.statements, name="statements"),
    path("statements/upload/", views.statement_upload, name="statement_upload"),
    path("statements/new/", views.statement_create, name="statement_create"),
    path("statements/<int:pk>/", views.statement_edit, name="statement_edit"),
    path("statements/<int:pk>/status.json", views.statement_status, name="statement_status"),
    path("statements/<int:pk>/delete/", views.statement_delete, name="statement_delete"),
    path("other-income/new/", views.other_income_create, name="other_income_create"),
    path("other-income/<int:pk>/", views.other_income_edit, name="other_income_edit"),
    path("books/<int:year>/", views.books_view, name="books"),
    path("books/<int:year>/export/<str:kind>.csv", views.books_export, name="books_export"),
    path("journal/<int:year>/", views.journal_view, name="journal"),
    path("journal/<int:year>/export/<str:kind>.csv", views.journal_export, name="journal_export"),
    path("journal/<int:year>/opening/", views.opening_balance, name="opening_balance"),
    path("journal/<int:year>/manual/new/", views.manual_entry_create, name="manual_entry_create"),
    path("journal/manual/<int:pk>/delete/", views.manual_entry_delete, name="manual_entry_delete"),
    path("forecast/<int:year>/", views.forecast_view, name="forecast"),
    path("filings/", views.filings, name="filings"),
    path("filings/sheet/", views.filing_sheet_view, name="filing_sheet"),
]
