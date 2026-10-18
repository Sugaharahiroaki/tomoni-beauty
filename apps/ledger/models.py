import calendar
import uuid
from datetime import date
from pathlib import Path

from django.db import models

from apps.core.models import TenantManager, TimeStampedModel

from .categories import CATEGORY_CHOICES, category_account, category_label, deduction_category
from .tax import BLUE_DEDUCTION_CHOICES


def receipt_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"stylist_{instance.stylist_id}/receipts/{uuid.uuid4().hex}{ext}"


def statement_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"stylist_{instance.stylist_id}/statements/{uuid.uuid4().hex}{ext}"


class Receipt(TimeStampedModel):
    """レシート・領収書の画像。OCR → Expense の下書き。"""

    class Status(models.TextChoices):
        PENDING = "pending", "受付"
        PROCESSING = "processing", "読み取り中"
        DONE = "done", "読み取り完了（確認待ち）"
        APPLIED = "applied", "経費に登録済み"
        FAILED = "failed", "失敗"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="receipts")
    file = models.FileField("画像/PDF", upload_to=receipt_path)
    ocr_raw = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "レシート"
        verbose_name_plural = "レシート"

    def __str__(self):
        return f"レシート #{self.pk} ({self.get_status_display()})"

    @property
    def is_processing(self) -> bool:
        return self.status in (self.Status.PENDING, self.Status.PROCESSING)


class IncomeStatement(TimeStampedModel):
    """サロンからの報酬明細（月単位）。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "確認待ち"
        CONFIRMED = "confirmed", "確定"
        PROCESSING = "processing", "読み取り中"
        FAILED = "failed", "読み取り失敗"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="income_statements")
    year = models.PositiveSmallIntegerField("年")
    month = models.PositiveSmallIntegerField("月")
    salon_name = models.CharField("サロン名", max_length=100, blank=True)
    gross_sales = models.PositiveIntegerField("技術売上（円）", null=True, blank=True)
    commission_rate_pct = models.DecimalField("歩合率(%)", max_digits=5, decimal_places=2, null=True, blank=True)
    commission_amount = models.PositiveIntegerField("報酬額（控除前・円）", default=0)
    deductions = models.JSONField("控除項目", default=list, blank=True)  # [{"label": str, "amount": int}]
    withholding_tax = models.PositiveIntegerField("源泉徴収税額（円）", default=0)
    net_paid = models.PositiveIntegerField("差引支給額（円）", default=0)
    paid_on = models.DateField("支払日", null=True, blank=True)
    document = models.FileField("明細の画像/PDF", upload_to=statement_path, blank=True, null=True)
    ocr_raw = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    error = models.TextField(blank=True)
    notes = models.TextField("メモ", blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-year", "-month", "-created_at"]
        verbose_name = "報酬明細"
        verbose_name_plural = "報酬明細"

    def __str__(self):
        return f"{self.year}/{self.month:02d} {self.salon_name} ¥{self.commission_amount:,}"

    @property
    def period_end(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def deductions_total(self) -> int:
        return sum(int(d.get("amount") or 0) for d in (self.deductions or []))

    @property
    def balance_diff(self) -> int:
        """報酬 − 控除 − 源泉 − 支給額。0 でなければ読み取り漏れの可能性。"""
        return self.commission_amount - self.deductions_total - self.withholding_tax - self.net_paid

    @property
    def is_processing(self) -> bool:
        return self.status == self.Status.PROCESSING

    def sync_deduction_expenses(self):
        """控除項目を経費（報酬から天引き）として同期する。"""
        existing = {e.description: e for e in self.deduction_expenses.all()}
        keep = set()
        for d in self.deductions or []:
            label = (d.get("label") or "控除").strip()[:200]
            amount = int(d.get("amount") or 0)
            if amount <= 0:
                continue
            keep.add(label)
            exp = existing.get(label)
            if exp is None:
                exp = Expense(stylist=self.stylist, statement=self, payment_method=Expense.Payment.STATEMENT, receipt=None)
            exp.date = self.period_end
            exp.amount = amount
            exp.category = exp.category if exp.pk else deduction_category(label)
            exp.vendor = self.salon_name
            exp.description = label
            exp.status = Expense.Status.CONFIRMED if self.status == self.Status.CONFIRMED else Expense.Status.DRAFT
            exp.save()
        for label, exp in existing.items():
            if label not in keep:
                exp.delete()


class Expense(TimeStampedModel):
    class Payment(models.TextChoices):
        CASH = "cash", "現金"
        BANK = "bank", "事業用の口座・カード"
        PRIVATE = "private", "個人の財布・カード（事業主借）"
        STATEMENT = "statement", "報酬から天引き"

    class Status(models.TextChoices):
        DRAFT = "draft", "確認待ち"
        CONFIRMED = "confirmed", "確定"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="expenses")
    date = models.DateField("日付")
    amount = models.PositiveIntegerField("金額（円・税込）")
    category = models.CharField("科目", max_length=20, choices=CATEGORY_CHOICES, default="misc")
    vendor = models.CharField("支払先", max_length=100, blank=True)
    description = models.CharField("内容", max_length=200, blank=True)
    business_ratio = models.PositiveSmallIntegerField("事業使用割合(%)", default=100)
    payment_method = models.CharField("支払方法", max_length=10, choices=Payment.choices, default=Payment.PRIVATE)
    receipt = models.OneToOneField(Receipt, on_delete=models.SET_NULL, null=True, blank=True, related_name="expense")
    statement = models.ForeignKey(IncomeStatement, on_delete=models.CASCADE, null=True, blank=True, related_name="deduction_expenses")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    notes = models.CharField("メモ", max_length=200, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "経費"
        verbose_name_plural = "経費"

    def __str__(self):
        return f"{self.date} {self.category_label} ¥{self.amount:,}"

    @property
    def category_label(self) -> str:
        return category_label(self.category)

    @property
    def account_name(self) -> str:
        return category_account(self.category)

    @property
    def business_amount(self) -> int:
        ratio = min(max(self.business_ratio, 0), 100)
        return int(round(self.amount * ratio / 100))


class OtherIncome(TimeStampedModel):
    """報酬以外の収入（商品販売・講師料など）。"""

    class ReceivedTo(models.TextChoices):
        CASH = "cash", "現金"
        BANK = "bank", "普通預金"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="other_incomes")
    date = models.DateField("日付")
    amount = models.PositiveIntegerField("金額（円）")
    description = models.CharField("内容", max_length=200)
    withholding_tax = models.PositiveIntegerField("源泉徴収税額", default=0)
    received_to = models.CharField(max_length=10, choices=ReceivedTo.choices, default=ReceivedTo.BANK)

    objects = TenantManager()

    class Meta:
        ordering = ["-date"]
        verbose_name = "その他収入"
        verbose_name_plural = "その他収入"

    def __str__(self):
        return f"{self.date} {self.description} ¥{self.amount:,}"


class OpeningBalance(models.Model):
    """年初残高（複式簿記用）。"""

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="opening_balances")
    year = models.PositiveSmallIntegerField("年")
    cash = models.PositiveIntegerField("現金", default=0)
    bank = models.PositiveIntegerField("普通預金", default=0)
    receivable = models.PositiveIntegerField("売掛金（前年12月分の未入金報酬など）", default=0)

    class Meta:
        unique_together = [("stylist", "year")]

    @property
    def capital(self) -> int:
        return self.cash + self.bank + self.receivable


class ManualJournalEntry(TimeStampedModel):
    """自動仕訳で表せない取引の手入力（複式簿記）。"""

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="manual_journal_entries")
    date = models.DateField("日付")
    debit_account = models.CharField("借方科目", max_length=30)
    credit_account = models.CharField("貸方科目", max_length=30)
    amount = models.PositiveIntegerField("金額")
    description = models.CharField("摘要", max_length=200, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["date", "id"]


class TaxSettings(TimeStampedModel):
    """手取り見込み計算の前提（美容師ごと）。"""

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, related_name="tax_settings")
    blue_deduction = models.PositiveIntegerField("青色申告特別控除", choices=BLUE_DEDUCTION_CHOICES, default=100_000)
    pension_monthly = models.PositiveIntegerField("国民年金（月額）", default=17_920)
    include_pension = models.BooleanField("国民年金を含める", default=True)
    nhi_rate_pct = models.DecimalField("国民健康保険の概算料率(%)", max_digits=5, decimal_places=2, default=11)
    nhi_cap = models.PositiveIntegerField("国民健康保険の年間上限", default=1_090_000)
    other_deductions = models.PositiveIntegerField("その他の所得控除（生命保険料控除など）", default=0)
    projected_monthly_revenue = models.PositiveIntegerField("見込み月収（未入力なら実績平均）", null=True, blank=True)
    projected_monthly_expenses = models.PositiveIntegerField("見込み月間経費（未入力なら実績平均）", null=True, blank=True)

    class Meta:
        verbose_name = "税務設定"
        verbose_name_plural = "税務設定"

    def params(self, year: int):
        from .tax import TaxParams

        return TaxParams(
            year=year,
            blue_deduction=self.blue_deduction,
            pension_monthly=self.pension_monthly,
            include_pension=self.include_pension,
            nhi_rate_pct=float(self.nhi_rate_pct),
            nhi_cap=self.nhi_cap,
            other_deductions=self.other_deductions,
        )


class FilingProfile(TimeStampedModel):
    """開業届・青色申告承認申請書の記入項目。"""

    class Bookkeeping(models.TextChoices):
        SIMPLE = "simple", "簡易簿記（10万円控除）"
        DOUBLE = "double", "複式簿記（55万/65万円控除）"

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, related_name="filing_profile")
    full_name = models.CharField("氏名", max_length=50, blank=True)
    full_name_kana = models.CharField("フリガナ", max_length=50, blank=True)
    birth_date = models.DateField("生年月日", null=True, blank=True)
    postal_code = models.CharField("郵便番号", max_length=8, blank=True)
    address = models.CharField("住所（納税地）", max_length=200, blank=True)
    phone = models.CharField("電話番号", max_length=20, blank=True)
    tax_office = models.CharField("所轄税務署", max_length=50, blank=True, help_text="例: 渋谷")
    business_name = models.CharField("屋号", max_length=50, blank=True)
    business_type = models.CharField("職業", max_length=50, default="美容業")
    business_description = models.CharField("事業の概要", max_length=200, default="業務委託契約に基づく美容施術（カット・カラー等）")
    opened_on = models.DateField("開業日", null=True, blank=True)
    income_type = models.CharField("所得の種類", max_length=20, default="事業所得")
    bookkeeping = models.CharField("簿記方式", max_length=10, choices=Bookkeeping.choices, default=Bookkeeping.SIMPLE)
    books = models.JSONField("備付帳簿名", default=list, blank=True)
    uses_etax = models.BooleanField("e-Taxで申告する", default=True)
    start_blue_year = models.PositiveSmallIntegerField("青色申告を始める年", null=True, blank=True)
    submit_blue_with_opening = models.BooleanField("開業届と同時に青色申告承認申請書を出す", default=True)
    has_employees = models.BooleanField("従業員を雇う", default=False)

    class Meta:
        verbose_name = "開業届・青色申告の記入情報"
        verbose_name_plural = "開業届・青色申告の記入情報"
