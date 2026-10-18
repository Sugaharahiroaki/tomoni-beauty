from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.dates import today_local
from apps.core.decorators import stylist_required
from apps.core.jobs import enqueue

from . import books, exports, journal
from .filings import filing_sheet, required_books
from .forms import ExpenseForm, FilingProfileForm, IncomeStatementForm, ManualJournalEntryForm, OpeningBalanceForm, OtherIncomeForm, TaxSettingsForm
from .models import Expense, FilingProfile, IncomeStatement, ManualJournalEntry, OpeningBalance, OtherIncome, Receipt
from .services import apply_receipt, available_years, confirm_statement, forecast, get_tax_settings, receipt_initial, unconfirm_statement

MAX_UPLOAD = 25 * 1024 * 1024


def _year(request) -> int:
    try:
        return int(request.GET.get("year") or today_local().year)
    except ValueError:
        return today_local().year


# ---------------------------------------------------------------------------
# ホーム
# ---------------------------------------------------------------------------
@stylist_required
def dashboard(request):
    stylist = request.stylist
    today = today_local()
    year = _year(request)
    overview = books.year_overview(stylist, year)
    this_month_exp = sum(e.business_amount for e in Expense.objects.filter(stylist=stylist, status=Expense.Status.CONFIRMED, date__year=today.year, date__month=today.month))
    pending = {
        "receipts": Receipt.objects.filter(stylist=stylist, status=Receipt.Status.DONE).count(),
        "receipts_failed": Receipt.objects.filter(stylist=stylist, status=Receipt.Status.FAILED).count(),
        "statements": IncomeStatement.objects.filter(stylist=stylist, status__in=[IncomeStatement.Status.DRAFT, IncomeStatement.Status.FAILED]).count(),
        "expenses": Expense.objects.filter(stylist=stylist, status=Expense.Status.DRAFT, statement__isnull=True).count(),
    }
    fc = forecast(stylist, year) if overview["revenue"] else None
    context = {"year": year, "years": available_years(stylist), "overview": overview, "this_month_exp": this_month_exp, "pending": pending, "forecast": fc, "today": today}
    return render(request, "ledger/dashboard.html", context)


# ---------------------------------------------------------------------------
# レシート
# ---------------------------------------------------------------------------
@stylist_required
def receipts(request):
    qs = Receipt.objects.filter(stylist=request.stylist)
    return render(request, "ledger/receipts.html", {"pending": qs.exclude(status=Receipt.Status.APPLIED)[:50], "applied": qs.filter(status=Receipt.Status.APPLIED)[:20]})


@stylist_required
@require_POST
def receipt_upload(request):
    files = request.FILES.getlist("file")
    if not files:
        messages.error(request, "写真を選んでください")
        return redirect("ledger:receipts")
    created = []
    for f in files[:10]:
        if f.size > MAX_UPLOAD:
            messages.error(request, f"{f.name} は大きすぎます（25MBまで）")
            continue
        receipt = Receipt.objects.create(stylist=request.stylist, file=f)
        enqueue("apps.ledger.tasks.run_receipt_ocr", receipt.id)
        created.append(receipt)
    if len(created) == 1:
        return redirect("ledger:receipt_review", pk=created[0].pk)
    messages.success(request, f"{len(created)}枚のレシートを読み取り中です")
    return redirect("ledger:receipts")


@stylist_required
def receipt_review(request, pk: int):
    receipt = get_object_or_404(Receipt, pk=pk, stylist=request.stylist)
    if receipt.status == Receipt.Status.APPLIED and getattr(receipt, "expense", None):
        return redirect("ledger:expense_edit", pk=receipt.expense.pk)
    form = None
    if receipt.status in (Receipt.Status.DONE, Receipt.Status.FAILED):
        form = ExpenseForm(request.POST or None, initial=receipt_initial(receipt) if receipt.status == Receipt.Status.DONE else {"date": today_local()})
        if request.method == "POST" and form.is_valid():
            expense = form.save(commit=False)
            apply_receipt(receipt, expense)
            messages.success(request, "経費に登録しました")
            return redirect("ledger:receipts")
    return render(request, "ledger/receipt_review.html", {"receipt": receipt, "form": form, "ocr": receipt.ocr_raw})


@stylist_required
def receipt_status(request, pk: int):
    receipt = get_object_or_404(Receipt, pk=pk, stylist=request.stylist)
    return JsonResponse({"status": receipt.status, "done": not receipt.is_processing, "error": receipt.error})


@stylist_required
@require_POST
def receipt_delete(request, pk: int):
    receipt = get_object_or_404(Receipt, pk=pk, stylist=request.stylist)
    receipt.file.delete(save=False)
    receipt.delete()
    return redirect("ledger:receipts")


@stylist_required
@require_POST
def receipt_retry(request, pk: int):
    receipt = get_object_or_404(Receipt, pk=pk, stylist=request.stylist)
    receipt.status = Receipt.Status.PENDING
    receipt.save(update_fields=["status", "updated_at"])
    enqueue("apps.ledger.tasks.run_receipt_ocr", receipt.id)
    return redirect("ledger:receipt_review", pk=pk)


# ---------------------------------------------------------------------------
# 経費
# ---------------------------------------------------------------------------
@stylist_required
def expenses(request):
    year = _year(request)
    month = request.GET.get("month")
    qs = Expense.objects.filter(stylist=request.stylist, date__year=year).select_related("statement", "receipt")
    if month and month.isdigit():
        qs = qs.filter(date__month=int(month))
    summary = books.monthly_category_summary(request.stylist, year)
    return render(request, "ledger/expenses.html", {"expenses": qs[:300], "year": year, "month": int(month) if month and month.isdigit() else None, "summary": summary, "years": available_years(request.stylist), "months": range(1, 13)})


@stylist_required
def expense_create(request):
    form = ExpenseForm(request.POST or None, initial={"date": today_local(), "business_ratio": 100})
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.stylist = request.stylist
        expense.status = Expense.Status.CONFIRMED
        expense.save()
        messages.success(request, "経費を登録しました")
        return redirect("ledger:expenses")
    return render(request, "ledger/expense_form.html", {"form": form, "is_new": True})


@stylist_required
def expense_edit(request, pk: int):
    expense = get_object_or_404(Expense, pk=pk, stylist=request.stylist)
    form = ExpenseForm(request.POST or None, instance=expense)
    if expense.statement_id:
        for name in ("date", "amount", "vendor", "description", "payment_method"):
            form.fields[name].disabled = True
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        if not expense.statement_id:
            obj.status = Expense.Status.CONFIRMED
        obj.save()
        messages.success(request, "保存しました")
        return redirect("ledger:expenses")
    return render(request, "ledger/expense_form.html", {"form": form, "expense": expense, "is_new": False})


@stylist_required
@require_POST
def expense_delete(request, pk: int):
    expense = get_object_or_404(Expense, pk=pk, stylist=request.stylist)
    if expense.statement_id:
        messages.error(request, "報酬明細の控除項目は明細側で編集してください")
        return redirect("ledger:statement_edit", pk=expense.statement_id)
    if expense.receipt_id:
        expense.receipt.status = Receipt.Status.DONE
        expense.receipt.save(update_fields=["status", "updated_at"])
    expense.delete()
    messages.info(request, "削除しました")
    return redirect("ledger:expenses")


@stylist_required
def expenses_csv(request):
    year = _year(request)
    data = exports.expenses_csv(books.confirmed_expenses(request.stylist, year))
    return _csv_response(data, f"expenses-{year}.csv")


# ---------------------------------------------------------------------------
# 報酬明細
# ---------------------------------------------------------------------------
@stylist_required
def statements(request):
    year = _year(request)
    qs = IncomeStatement.objects.filter(stylist=request.stylist, year=year)
    others = OtherIncome.objects.filter(stylist=request.stylist, date__year=year)
    summary = books.income_summary(request.stylist, year)
    return render(request, "ledger/statements.html", {"statements": qs, "others": others, "year": year, "years": available_years(request.stylist), "summary": summary})


@stylist_required
@require_POST
def statement_upload(request):
    f = request.FILES.get("file")
    if not f:
        messages.error(request, "明細の写真かPDFを選んでください")
        return redirect("ledger:statements")
    if f.size > MAX_UPLOAD:
        messages.error(request, "ファイルが大きすぎます（25MBまで）")
        return redirect("ledger:statements")
    today = today_local()
    statement = IncomeStatement.objects.create(stylist=request.stylist, year=today.year, month=today.month, document=f, status=IncomeStatement.Status.PROCESSING, salon_name=request.stylist.salon_name)
    enqueue("apps.ledger.tasks.run_statement_ocr", statement.id)
    return redirect("ledger:statement_edit", pk=statement.pk)


@stylist_required
def statement_create(request):
    today = today_local()
    initial = {"year": today.year, "month": today.month - 1 or 12, "salon_name": request.stylist.salon_name, "commission_rate_pct": request.stylist.commission_rate, "withholding_tax": 0}
    form = IncomeStatementForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        statement = form.save(commit=False)
        statement.stylist = request.stylist
        statement.status = IncomeStatement.Status.DRAFT
        statement.save()
        statement.sync_deduction_expenses()
        return redirect("ledger:statement_edit", pk=statement.pk)
    return render(request, "ledger/statement_form.html", {"form": form, "is_new": True})


@stylist_required
def statement_edit(request, pk: int):
    statement = get_object_or_404(IncomeStatement, pk=pk, stylist=request.stylist)
    form = IncomeStatementForm(request.POST or None, instance=statement)
    if request.method == "POST" and not statement.is_processing and form.is_valid():
        statement = form.save()
        if request.POST.get("action") == "confirm":
            confirm_statement(statement)
            messages.success(request, "報酬明細を確定しました。控除項目は経費に反映されています。")
            return redirect("ledger:statements")
        if request.POST.get("action") == "unconfirm":
            unconfirm_statement(statement)
            messages.info(request, "確定を解除しました")
        else:
            statement.sync_deduction_expenses()
            messages.success(request, "保存しました")
        return redirect("ledger:statement_edit", pk=pk)
    return render(request, "ledger/statement_form.html", {"form": form, "statement": statement, "is_new": False})


@stylist_required
def statement_status(request, pk: int):
    statement = get_object_or_404(IncomeStatement, pk=pk, stylist=request.stylist)
    return JsonResponse({"status": statement.status, "done": not statement.is_processing, "error": statement.error})


@stylist_required
@require_POST
def statement_delete(request, pk: int):
    statement = get_object_or_404(IncomeStatement, pk=pk, stylist=request.stylist)
    if statement.document:
        statement.document.delete(save=False)
    statement.delete()
    messages.info(request, "削除しました")
    return redirect("ledger:statements")


@stylist_required
def other_income_create(request):
    form = OtherIncomeForm(request.POST or None, initial={"date": today_local()})
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.stylist = request.stylist
        obj.save()
        messages.success(request, "収入を登録しました")
        return redirect("ledger:statements")
    return render(request, "ledger/other_income_form.html", {"form": form})


@stylist_required
def other_income_edit(request, pk: int):
    obj = get_object_or_404(OtherIncome, pk=pk, stylist=request.stylist)
    form = OtherIncomeForm(request.POST or None, instance=obj)
    if request.method == "POST":
        if "delete" in request.POST:
            obj.delete()
            return redirect("ledger:statements")
        if form.is_valid():
            form.save()
            return redirect("ledger:statements")
    return render(request, "ledger/other_income_form.html", {"form": form, "obj": obj})


# ---------------------------------------------------------------------------
# 簡易簿記の帳簿
# ---------------------------------------------------------------------------
@stylist_required
def books_view(request, year: int):
    tab = request.GET.get("tab", "summary")
    stylist = request.stylist
    context = {"year": year, "tab": tab, "years": available_years(stylist), "summary": books.monthly_category_summary(stylist, year), "income": books.income_summary(stylist, year)}
    if tab == "expenses":
        context["ledger"] = books.expense_ledger(stylist, year)
    elif tab == "receivable":
        context["receivable"] = books.receivable_ledger(stylist, year)
    elif tab == "cash":
        context["cash"] = books.cash_book(stylist, year)
    return render(request, "ledger/books.html", context)


@stylist_required
def books_export(request, year: int, kind: str):
    stylist = request.stylist
    if kind == "expenses":
        return _csv_response(exports.expenses_csv(books.confirmed_expenses(stylist, year)), f"expenses-{year}.csv")
    if kind == "income":
        return _csv_response(exports.income_csv(books.confirmed_statements(stylist, year)), f"income-{year}.csv")
    raise Http404


# ---------------------------------------------------------------------------
# 複式簿記（第3段階）
# ---------------------------------------------------------------------------
@stylist_required
def journal_view(request, year: int):
    tab = request.GET.get("tab", "journal")
    stylist = request.stylist
    ts = get_tax_settings(stylist)
    decision = journal.decision_sheet(stylist, year, ts.blue_deduction)
    context = {
        "year": year,
        "tab": tab,
        "years": available_years(stylist),
        "entries": decision["entries"],
        "ledger": journal.general_ledger(decision["entries"]) if tab == "ledger" else None,
        "trial": decision["trial_balance"],
        "pl": decision["pl"],
        "bs": decision["bs"],
        "decision": decision,
        "opening": OpeningBalance.objects.filter(stylist=stylist, year=year).first(),
        "manual_entries": ManualJournalEntry.objects.filter(stylist=stylist, date__year=year),
        "blue_deduction": ts.blue_deduction,
    }
    return render(request, "ledger/journal.html", context)


@stylist_required
def journal_export(request, year: int, kind: str):
    stylist = request.stylist
    entries = journal.all_entries(stylist, year)
    if kind == "generic":
        return _csv_response(exports.journal_csv_generic(entries), f"journal-{year}.csv")
    if kind == "yayoi":
        return _csv_response(exports.journal_csv_yayoi(entries), f"yayoi-journal-{year}.csv", encoding="cp932")
    if kind == "freee":
        data = exports.freee_csv(books.confirmed_expenses(stylist, year), books.confirmed_statements(stylist, year), books.other_incomes(stylist, year))
        return _csv_response(data, f"freee-{year}.csv")
    if kind == "etax":
        ts = get_tax_settings(stylist)
        decision = journal.decision_sheet(stylist, year, ts.blue_deduction)
        fc = forecast(stylist, year)
        return _csv_response(exports.etax_summary_csv(decision, fc["estimate"]), f"etax-summary-{year}.csv")
    raise Http404


@stylist_required
def opening_balance(request, year: int):
    obj = OpeningBalance.objects.filter(stylist=request.stylist, year=year).first()
    form = OpeningBalanceForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        ob = form.save(commit=False)
        ob.stylist = request.stylist
        ob.year = year
        ob.save()
        messages.success(request, "期首残高を保存しました")
        return redirect(f"/money/journal/{year}/?tab=bs")
    return render(request, "ledger/opening_form.html", {"form": form, "year": year})


@stylist_required
def manual_entry_create(request, year: int):
    form = ManualJournalEntryForm(request.POST or None, initial={"date": today_local()})
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.stylist = request.stylist
        entry.save()
        messages.success(request, "仕訳を追加しました")
        return redirect(f"/money/journal/{entry.date.year}/?tab=journal")
    return render(request, "ledger/manual_entry_form.html", {"form": form, "year": year})


@stylist_required
@require_POST
def manual_entry_delete(request, pk: int):
    entry = get_object_or_404(ManualJournalEntry, pk=pk, stylist=request.stylist)
    year = entry.date.year
    entry.delete()
    return redirect(f"/money/journal/{year}/?tab=journal")


# ---------------------------------------------------------------------------
# 手取り見込み・税務設定
# ---------------------------------------------------------------------------
@stylist_required
def forecast_view(request, year: int):
    ts = get_tax_settings(request.stylist)
    form = TaxSettingsForm(request.POST or None, instance=ts)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "前提を保存して再計算しました")
        return redirect("ledger:forecast", year=year)
    fc = forecast(request.stylist, year)
    return render(request, "ledger/forecast.html", {"form": form, "fc": fc, "year": year, "years": available_years(request.stylist)})


# ---------------------------------------------------------------------------
# 開業届・青色申告承認申請書
# ---------------------------------------------------------------------------
@stylist_required
def filings(request):
    profile, _ = FilingProfile.objects.get_or_create(stylist=request.stylist, defaults={"full_name": request.stylist.display_name, "books": required_books("simple")})
    form = FilingProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.books = form.cleaned_data.get("books") or required_books(obj.bookkeeping)
        obj.save()
        messages.success(request, "保存しました")
        return redirect("ledger:filing_sheet")
    return render(request, "ledger/filings.html", {"form": form, "profile": profile})


@stylist_required
def filing_sheet_view(request):
    profile = get_object_or_404(FilingProfile, stylist=request.stylist)
    if not profile.opened_on:
        messages.error(request, "開業日を入力してください")
        return redirect("ledger:filings")
    return render(request, "ledger/filing_sheet.html", {"profile": profile, "sheet": filing_sheet(profile)})


def _csv_response(text: str, filename: str, encoding: str = "utf-8") -> HttpResponse:
    body = exports.encode(text, encoding)
    content_type = "text/csv; charset=shift_jis" if encoding == "cp932" else "text/csv; charset=utf-8"
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
