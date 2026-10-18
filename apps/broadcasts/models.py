from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models

from apps.core.models import TenantManager, TimeStampedModel


def rich_menu_image_path(instance, filename):
    return f"stylist_{instance.stylist_id}/richmenu/{filename}"


class AvailabilitySlot(TimeStampedModel):
    """空き枠（日・開始・終了）。"""

    class Status(models.TextChoices):
        OPEN = "open", "空き"
        FILLED = "filled", "埋まった"
        CLOSED = "closed", "取り下げ"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="availability_slots")
    date = models.DateField("日付")
    start_time = models.TimeField("開始")
    end_time = models.TimeField("終了")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    note = models.CharField("メモ", max_length=100, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["date", "start_time"]
        verbose_name = "空き枠"
        verbose_name_plural = "空き枠"

    def __str__(self):
        return self.label

    @property
    def hours(self) -> Decimal:
        start = datetime.combine(self.date, self.start_time)
        end = datetime.combine(self.date, self.end_time)
        if end <= start:
            end += timedelta(days=1)
        return (Decimal((end - start).total_seconds()) / Decimal(3600)).quantize(Decimal("0.1"))

    @property
    def label(self) -> str:
        weekdays = "月火水木金土日"
        return f"{self.date.month}/{self.date.day}({weekdays[self.date.weekday()]}) {self.start_time:%H:%M}〜{self.end_time:%H:%M}"


class WaitlistEntry(TimeStampedModel):
    """キャンセル待ち・空き枠希望者。"""

    class Status(models.TextChoices):
        ACTIVE = "active", "待ち"
        NOTIFIED = "notified", "案内済み"
        BOOKED = "booked", "予約済み"
        CLOSED = "closed", "終了"

    class Source(models.TextChoices):
        RICHMENU = "richmenu", "リッチメニュー"
        MANUAL = "manual", "手入力"
        MESSAGE = "message", "LINEメッセージ"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="waitlist_entries")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="waitlist_entries")
    preferred_timing = models.CharField("希望時期", max_length=100, blank=True)
    note = models.CharField("メモ", max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    notified_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "キャンセル待ち"
        verbose_name_plural = "キャンセル待ち"

    def __str__(self):
        return f"{self.customer} ({self.get_status_display()})"


class Broadcast(TimeStampedModel):
    """一斉・セグメント配信。送信は必ず美容師の確認後、通数と対象人数を表示してから。"""

    class Kind(models.TextChoices):
        ANNOUNCEMENT = "announcement", "全体告知"
        SEGMENT = "segment", "絞り込み配信"
        AVAILABILITY = "availability", "空き枠の案内"
        WAITLIST = "waitlist", "キャンセル待ちへの案内"

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        SENDING = "sending", "送信中"
        SENT = "sent", "送信済み"
        FAILED = "failed", "失敗"
        CANCELLED = "cancelled", "取り消し"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="broadcasts")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.ANNOUNCEMENT)
    title = models.CharField("タイトル（管理用）", max_length=100)
    body = models.TextField("本文")
    segment = models.JSONField("絞り込み条件", default=dict, blank=True)
    slots = models.ManyToManyField(AvailabilitySlot, blank=True, related_name="broadcasts")
    tracked_link = models.ForeignKey("lineapp.TrackedLink", on_delete=models.SET_NULL, null=True, blank=True, related_name="broadcasts")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    target_count = models.PositiveIntegerField(default=0)
    planned_messages = models.PositiveIntegerField(default=0)
    quota_limit_snapshot = models.PositiveIntegerField(null=True, blank=True)
    quota_used_snapshot = models.PositiveIntegerField(null=True, blank=True)
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    ai_alternatives = models.JSONField(default=list, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "一斉配信"
        verbose_name_plural = "一斉配信"

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def is_editable(self) -> bool:
        return self.status == self.Status.DRAFT


class BroadcastRecipient(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待機"
        SENT = "sent", "送信"
        FAILED = "failed", "失敗"

    broadcast = models.ForeignKey(Broadcast, on_delete=models.CASCADE, related_name="recipients")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="broadcast_receipts")
    line_user_id = models.CharField(max_length=64)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=200, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("broadcast", "customer")]


class RichMenu(TimeStampedModel):
    """リッチメニュー: 予約する（ホットペッパー）／相談する／キャンセル待ちに登録。"""

    class Status(models.TextChoices):
        DRAFT = "draft", "未公開"
        PUBLISHED = "published", "公開中"
        FAILED = "failed", "失敗"

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, related_name="rich_menu")
    line_rich_menu_id = models.CharField(max_length=64, blank=True)
    image = models.ImageField("メニュー画像（任意・2500×843）", upload_to=rich_menu_image_path, blank=True, null=True)
    reserve_label = models.CharField("ボタン1", max_length=20, default="予約する")
    consult_label = models.CharField("ボタン2", max_length=20, default="相談する")
    waitlist_label = models.CharField("ボタン3", max_length=20, default="キャンセル待ち登録")
    consult_message = models.CharField("「相談する」で送られる文", max_length=100, default="相談したいことがあります")
    waitlist_reply = models.CharField(
        "キャンセル待ち登録時の自動返信（Reply・無料）",
        max_length=300,
        default="キャンセル待ちに登録しました🍀 空きが出たらこのLINEでご連絡します。ご希望の曜日や時間帯があれば返信で教えてください。",
    )
    auto_reply_enabled = models.BooleanField("登録時に自動返信する（事前承認）", default=True)
    chat_bar_text = models.CharField("メニューバーの文字", max_length=14, default="メニュー")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    tracked_link = models.ForeignKey("lineapp.TrackedLink", on_delete=models.SET_NULL, null=True, blank=True, related_name="rich_menus")

    class Meta:
        verbose_name = "リッチメニュー"
        verbose_name_plural = "リッチメニュー"

    def __str__(self):
        return f"{self.stylist} リッチメニュー ({self.get_status_display()})"

    @property
    def labels(self) -> list[str]:
        return [self.reserve_label, self.consult_label, self.waitlist_label]
