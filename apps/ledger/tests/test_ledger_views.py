from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.ledger.models import Expense, FilingProfile, IncomeStatement, Receipt


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_receipt_upload_runs_ocr_and_applies(client_logged, stylist):
    resp = client_logged.post(reverse("ledger:receipt_upload"), {"file": SimpleUploadedFile("r.png", _png_bytes(), content_type="image/png")})
    assert resp.status_code == 302
    receipt = Receipt.objects.get(stylist=stylist)
    assert receipt.status == Receipt.Status.DONE  # Q_SYNC → 即時 Fake OCR
    assert receipt.ocr_raw["vendor"]
    page = client_logged.get(reverse("ledger:receipt_review", kwargs={"pk": receipt.pk}))
    assert page.status_code == 200
    resp = client_logged.post(
        reverse("ledger:receipt_review", kwargs={"pk": receipt.pk}),
        {"date": "2026-10-15", "amount": 6820, "category": "materials", "vendor": "BG", "description": "カラー剤", "business_ratio": 100, "payment_method": "private", "notes": ""},
    )
    assert resp.status_code == 302
    receipt.refresh_from_db()
    assert receipt.status == Receipt.Status.APPLIED
    exp = Expense.objects.get(receipt=receipt)
    assert exp.status == Expense.Status.CONFIRMED and exp.amount == 6820


def test_statement_upload_ocr_and_confirm(client_logged, stylist):
    resp = client_logged.post(reverse("ledger:statement_upload"), {"file": SimpleUploadedFile("s.png", _png_bytes(), content_type="image/png")})
    assert resp.status_code == 302
    st = IncomeStatement.objects.get(stylist=stylist)
    assert st.status == IncomeStatement.Status.DRAFT
    assert st.commission_amount == 210_000 and st.month == 9
    page = client_logged.get(reverse("ledger:statement_edit", kwargs={"pk": st.pk}))
    assert page.status_code == 200
    resp = client_logged.post(
        reverse("ledger:statement_edit", kwargs={"pk": st.pk}),
        {"year": 2026, "month": 9, "salon_name": "salon TOMONI", "gross_sales": 420000, "commission_rate_pct": 50, "commission_amount": 210000, "deductions_text": "材料費 21000\n振込手数料 440", "withholding_tax": 0, "net_paid": 188560, "paid_on": "2026-10-10", "notes": "", "action": "confirm"},
    )
    assert resp.status_code == 302
    st.refresh_from_db()
    assert st.status == IncomeStatement.Status.CONFIRMED
    assert Expense.objects.filter(statement=st, status=Expense.Status.CONFIRMED).count() == 2


def test_statement_form_rejects_bad_deduction_line(client_logged, stylist):
    resp = client_logged.post(reverse("ledger:statement_create"), {"year": 2026, "month": 8, "salon_name": "x", "commission_amount": 1000, "deductions_text": "材料費", "withholding_tax": 0, "net_paid": 1000, "notes": ""})
    assert resp.status_code == 200
    assert "名称 金額" in resp.content.decode()


def test_money_pages_render(client_logged, stylist):
    FilingProfile.objects.create(stylist=stylist, opened_on=date(2026, 4, 1))
    urls = [
        reverse("ledger:dashboard"),
        reverse("ledger:receipts"),
        reverse("ledger:expenses"),
        reverse("ledger:expenses") + "?year=2026&month=9",
        reverse("ledger:expense_create"),
        reverse("ledger:expenses_csv") + "?year=2026",
        reverse("ledger:statements"),
        reverse("ledger:statement_create"),
        reverse("ledger:other_income_create"),
        reverse("ledger:books", kwargs={"year": 2026}),
        reverse("ledger:books", kwargs={"year": 2026}) + "?tab=expenses",
        reverse("ledger:books", kwargs={"year": 2026}) + "?tab=receivable",
        reverse("ledger:books", kwargs={"year": 2026}) + "?tab=cash",
        reverse("ledger:books_export", kwargs={"year": 2026, "kind": "income"}),
        reverse("ledger:journal", kwargs={"year": 2026}),
        reverse("ledger:journal", kwargs={"year": 2026}) + "?tab=ledger",
        reverse("ledger:journal", kwargs={"year": 2026}) + "?tab=trial",
        reverse("ledger:journal", kwargs={"year": 2026}) + "?tab=pl",
        reverse("ledger:journal", kwargs={"year": 2026}) + "?tab=bs",
        reverse("ledger:journal", kwargs={"year": 2026}) + "?tab=decision",
        reverse("ledger:journal_export", kwargs={"year": 2026, "kind": "generic"}),
        reverse("ledger:journal_export", kwargs={"year": 2026, "kind": "yayoi"}),
        reverse("ledger:journal_export", kwargs={"year": 2026, "kind": "freee"}),
        reverse("ledger:journal_export", kwargs={"year": 2026, "kind": "etax"}),
        reverse("ledger:opening_balance", kwargs={"year": 2026}),
        reverse("ledger:manual_entry_create", kwargs={"year": 2026}),
        reverse("ledger:forecast", kwargs={"year": 2026}),
        reverse("ledger:filings"),
        reverse("ledger:filing_sheet"),
    ]
    for url in urls:
        resp = client_logged.get(url)
        assert resp.status_code == 200, f"{url} -> {resp.status_code}"


def test_ledger_tenant_isolation(client_logged, other_stylist):
    exp = Expense.objects.create(stylist=other_stylist, date=date(2026, 9, 1), amount=100, category="misc")
    assert client_logged.get(reverse("ledger:expense_edit", kwargs={"pk": exp.pk})).status_code == 404
