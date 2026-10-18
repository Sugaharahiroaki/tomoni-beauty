from django.db import models

from apps.core.models import TenantManager, TimeStampedModel


class Reservation(TimeStampedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "手入力"
        EMAIL = "email", "予約通知メール"
        LINE = "line", "LINE相談から"

    class Status(models.TextChoices):
        BOOKED = "booked", "予約中"
        VISITED = "visited", "来店済み"
        CANCELLED = "cancelled", "キャンセル"
        NO_SHOW = "no_show", "無断キャンセル"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="reservations")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="reservations", null=True, blank=True)
    customer_name_raw = models.CharField("予約者名（未照合）", max_length=100, blank=True)
    reserved_for = models.DateTimeField("予約日時")
    menu = models.CharField("メニュー", max_length=200, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.BOOKED)
    note = models.TextField("メモ", blank=True)
    # 「案内 → 予約」の効果測定。予約登録前 N 日以内に送った案内があれば紐付ける
    attributed_message = models.ForeignKey("lineapp.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="attributed_reservations")

    objects = TenantManager()

    class Meta:
        ordering = ["-reserved_for"]
        verbose_name = "予約"
        verbose_name_plural = "予約"

    def __str__(self):
        who = self.customer.name if self.customer else (self.customer_name_raw or "未照合")
        return f"{who} {self.reserved_for:%m/%d %H:%M}"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.BOOKED


class Visit(TimeStampedModel):
    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="visits")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="visits")
    visited_at = models.DateTimeField("来店日時")
    menu = models.CharField("メニュー", max_length=200, blank=True)
    price = models.PositiveIntegerField("単価(円)", null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField("施術時間(分)", null=True, blank=True)
    reservation = models.OneToOneField(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="visit")

    objects = TenantManager()

    class Meta:
        ordering = ["-visited_at"]
        verbose_name = "来店"
        verbose_name_plural = "来店"

    def __str__(self):
        return f"{self.customer} {self.visited_at:%Y/%m/%d}"


class ReservationEmail(TimeStampedModel):
    """予約通知メールの取り込みログ。本文は解析と手直しのために保持（不要になれば削除可）。"""

    class Status(models.TextChoices):
        PARSED = "parsed", "解析済み"
        APPLIED = "applied", "予約に反映"
        NEEDS_REVIEW = "needs_review", "要確認"
        UNPARSED = "unparsed", "読み取れず"
        IGNORED = "ignored", "無視"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="reservation_emails")
    received_at = models.DateTimeField("受信日時")
    sender = models.CharField("送信元", max_length=200, blank=True)
    subject = models.CharField("件名", max_length=300, blank=True)
    body = models.TextField("本文")
    source = models.CharField("取り込み元", max_length=10, default="n8n")  # n8n | paste
    parse_method = models.CharField(max_length=20, blank=True)  # regex | ai | regex+ai | failed
    parsed = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PARSED)
    reservation = models.ForeignKey(Reservation, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_emails")
    error = models.CharField(max_length=300, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "予約通知メール"
        verbose_name_plural = "予約通知メール"

    def __str__(self):
        return f"{self.subject[:30]} ({self.get_status_display()})"


class FollowUp(TimeStampedModel):
    class Kind(models.TextChoices):
        NEXT_VISIT = "next_visit", "次回来店の案内"
        AFTERCARE = "aftercare", "施術後の様子うかがい"
        CUSTOM = "custom", "その他"

    class Status(models.TextChoices):
        PENDING = "pending", "予定"
        DRAFT_READY = "draft_ready", "下書きあり"
        SENT = "sent", "送信済み"
        SKIPPED = "skipped", "見送り"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="follow_ups")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="follow_ups")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.NEXT_VISIT)
    due_date = models.DateField("予定日")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    karte = models.ForeignKey("karte.Karte", on_delete=models.SET_NULL, null=True, blank=True, related_name="follow_ups")
    draft = models.ForeignKey("drafts.Draft", on_delete=models.SET_NULL, null=True, blank=True, related_name="follow_ups")
    skip_reason = models.CharField(max_length=100, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["due_date"]
        verbose_name = "フォロー予定"
        verbose_name_plural = "フォロー予定"

    def __str__(self):
        return f"{self.customer} {self.get_kind_display()} {self.due_date}"
