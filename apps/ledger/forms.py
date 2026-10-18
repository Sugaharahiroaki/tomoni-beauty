import re

from django import forms

from .categories import ACCOUNT_ORDER
from .filings import required_books
from .models import Expense, FilingProfile, IncomeStatement, ManualJournalEntry, OpeningBalance, OtherIncome, TaxSettings


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["date", "amount", "category", "vendor", "description", "business_ratio", "payment_method", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "business_ratio": forms.NumberInput(attrs={"inputmode": "numeric", "min": 1, "max": 100}),
        }
        help_texts = {
            "business_ratio": "私用と兼用のもの（スマホ代など）は事業で使う割合に。100で全額",
            "category": "迷ったら近いものを選び、メモに内容を残す。経費になるかの最終判断は税理士に確認",
        }


class IncomeStatementForm(forms.ModelForm):
    deductions_text = forms.CharField(
        label="控除項目（1行に「名称 金額」）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "材料費 21000\n振込手数料 440"}),
    )

    class Meta:
        model = IncomeStatement
        fields = ["year", "month", "salon_name", "gross_sales", "commission_rate_pct", "commission_amount", "withholding_tax", "net_paid", "paid_on", "notes"]
        widgets = {
            "year": forms.NumberInput(attrs={"inputmode": "numeric", "min": 2020, "max": 2100}),
            "month": forms.NumberInput(attrs={"inputmode": "numeric", "min": 1, "max": 12}),
            "gross_sales": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "commission_rate_pct": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
            "commission_amount": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "withholding_tax": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "net_paid": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "paid_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.deductions:
            self.fields["deductions_text"].initial = "\n".join(f"{d.get('label', '')} {d.get('amount', 0)}" for d in self.instance.deductions)

    def clean_deductions_text(self):
        raw = self.cleaned_data.get("deductions_text") or ""
        out = []
        for line in raw.splitlines():
            line = line.strip().replace("，", ",").replace("、", " ")
            if not line:
                continue
            m = re.match(r"^(.*?)[\s,:：]+([0-9０-９,，]+)\s*円?$", line)
            if not m:
                raise forms.ValidationError(f"「{line}」は『名称 金額』の形式で入力してください")
            label = m.group(1).strip() or "控除"
            amount = int(re.sub(r"[^0-9０-９]", "", m.group(2)).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
            out.append({"label": label[:100], "amount": amount})
        return out

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.deductions = self.cleaned_data.get("deductions_text") or []
        if commit:
            obj.save()
        return obj


class OtherIncomeForm(forms.ModelForm):
    class Meta:
        model = OtherIncome
        fields = ["date", "amount", "description", "withholding_tax", "received_to"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "amount": forms.NumberInput(attrs={"inputmode": "numeric"}), "withholding_tax": forms.NumberInput(attrs={"inputmode": "numeric"})}


class OpeningBalanceForm(forms.ModelForm):
    class Meta:
        model = OpeningBalance
        fields = ["cash", "bank", "receivable"]
        widgets = {f: forms.NumberInput(attrs={"inputmode": "numeric"}) for f in ["cash", "bank", "receivable"]}


class ManualJournalEntryForm(forms.ModelForm):
    debit_account = forms.ChoiceField(label="借方科目", choices=[(a, a) for a in ACCOUNT_ORDER])
    credit_account = forms.ChoiceField(label="貸方科目", choices=[(a, a) for a in ACCOUNT_ORDER])

    class Meta:
        model = ManualJournalEntry
        fields = ["date", "debit_account", "credit_account", "amount", "description"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}), "amount": forms.NumberInput(attrs={"inputmode": "numeric"})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("debit_account") == cleaned.get("credit_account"):
            raise forms.ValidationError("借方と貸方に同じ科目は使えません")
        return cleaned


class TaxSettingsForm(forms.ModelForm):
    class Meta:
        model = TaxSettings
        fields = ["blue_deduction", "pension_monthly", "include_pension", "nhi_rate_pct", "nhi_cap", "other_deductions", "projected_monthly_revenue", "projected_monthly_expenses"]
        widgets = {f: forms.NumberInput(attrs={"inputmode": "numeric"}) for f in ["pension_monthly", "nhi_cap", "other_deductions", "projected_monthly_revenue", "projected_monthly_expenses"]}
        help_texts = {
            "nhi_rate_pct": "お住まいの市区町村の料率（所得割＋均等割をざっくり％換算）。分からなければ既定値のまま",
            "other_deductions": "生命保険料控除・配偶者控除・医療費控除などの合計。分からなければ0",
        }


class FilingProfileForm(forms.ModelForm):
    books = forms.MultipleChoiceField(label="備付帳簿名", required=False, widget=forms.CheckboxSelectMultiple, choices=[(b, b) for b in ["仕訳帳", "総勘定元帳", "現金出納帳", "売掛帳", "買掛帳", "経費帳", "固定資産台帳", "預金出納帳"]])

    class Meta:
        model = FilingProfile
        fields = [
            "full_name", "full_name_kana", "birth_date", "postal_code", "address", "phone", "tax_office", "business_name", "business_type",
            "business_description", "opened_on", "income_type", "bookkeeping", "books", "uses_etax", "start_blue_year", "submit_blue_with_opening", "has_employees",
        ]
        widgets = {"birth_date": forms.DateInput(attrs={"type": "date"}), "opened_on": forms.DateInput(attrs={"type": "date"}), "start_blue_year": forms.NumberInput(attrs={"inputmode": "numeric"})}

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("books"):
            cleaned["books"] = required_books(cleaned.get("bookkeeping", "simple"))
        return cleaned
