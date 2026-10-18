import re

from django.db import models
from django.utils import timezone

from apps.core.models import TenantManager, TimeStampedModel


class Tag(models.Model):
    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="tags")
    name = models.CharField("タグ名", max_length=30)

    objects = TenantManager()

    class Meta:
        unique_together = [("stylist", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Customer(TimeStampedModel):
    class Source(models.TextChoices):
        MANUAL = "manual", "手入力"
        LINE = "line", "LINE友だち追加"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="customers")
    name = models.CharField("お名前", max_length=100)
    kana = models.CharField("よみ", max_length=100, blank=True)
    call_name = models.CharField("LINEでの呼び方", max_length=50, blank=True, help_text="空欄なら「姓＋さん」")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    needs_review = models.BooleanField("要確認（LINEから自動作成）", default=False)

    # LINE 紐付け
    line_user_id = models.CharField("LINE userId", max_length=64, blank=True, null=True)
    line_display_name = models.CharField("LINE表示名", max_length=100, blank=True)
    line_picture_url = models.URLField(blank=True)
    line_followed = models.BooleanField("友だち状態", default=False)
    line_blocked_at = models.DateTimeField(null=True, blank=True)

    # 同意（それぞれ独立して記録する）
    contact_ok = models.BooleanField("LINE連絡OK", default=True)
    photo_ok = models.BooleanField("施術写真の掲載OK", default=False)
    face_ok = models.BooleanField("顔出しOK", default=False)
    story_ok = models.BooleanField("悩み・施術ストーリーの掲載OK", default=False)
    consent_updated_at = models.DateTimeField("同意の最終更新", null=True, blank=True)

    preferred_timing = models.CharField("希望来店時期・曜日", max_length=100, blank=True, help_text="例: 平日昼、土曜午前")
    memo = models.TextField("メモ（非公開）", blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="customers")

    objects = TenantManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "顧客"
        verbose_name_plural = "顧客"
        constraints = [
            models.UniqueConstraint(fields=["stylist", "line_user_id"], name="uniq_customer_line_user_per_stylist"),
        ]

    def __str__(self):
        return self.name

    # --- 表示 ---
    @property
    def surname(self) -> str:
        parts = re.split(r"[\s　]+", self.name.strip())
        return parts[0] if parts and parts[0] else self.name

    @property
    def display_call_name(self) -> str:
        if self.call_name:
            return self.call_name
        base = self.surname or self.name
        return f"{base}さん"

    @property
    def is_line_linked(self) -> bool:
        return bool(self.line_user_id)

    # --- 送信可否 ---
    @property
    def can_contact(self) -> bool:
        return self.contact_ok and self.line_blocked_at is None

    @property
    def contact_blocked_reason(self) -> str:
        if not self.contact_ok:
            return "連絡NGのお客様です"
        if self.line_blocked_at:
            return "LINEでブロックされています"
        return ""

    def record_consent_change(self):
        self.consent_updated_at = timezone.now()

    def consent_summary(self) -> list[tuple[str, bool]]:
        return [
            ("連絡", self.contact_ok),
            ("写真", self.photo_ok),
            ("顔出し", self.face_ok),
            ("ストーリー", self.story_ok),
        ]

    def context_for_ai(self) -> str:
        """AIに渡す「既知情報」。私的メモは渡さない。"""
        from apps.karte.models import Karte

        last = Karte.objects.filter(customer=self).order_by("-visited_on").first()
        bits = []
        if last:
            bits.append(f"前回来店 {last.visited_on.isoformat()}: {last.treatment_summary}")
            if last.next_check_items:
                bits.append("前回の次回確認事項: " + "、".join(last.next_check_items))
        if self.preferred_timing:
            bits.append(f"希望来店時期: {self.preferred_timing}")
        return "\n".join(bits)
