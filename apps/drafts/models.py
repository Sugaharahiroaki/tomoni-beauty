from django.db import models

from apps.core.models import TenantManager, TimeStampedModel


class Draft(TimeStampedModel):
    """LINEで送る文面の下書き。送信は必ず美容師の確認後。"""

    class Kind(models.TextChoices):
        THANKS_CARE = "thanks_care", "お礼＋お手入れ案内"
        NEXT_VISIT = "next_visit", "次回案内"
        REPLY = "reply", "返信案"
        CUSTOM = "custom", "その他"

    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        APPROVED = "approved", "確認済み"
        SENT = "sent", "送信済み"
        DISCARDED = "discarded", "破棄"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="drafts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="drafts", null=True, blank=True)
    karte = models.ForeignKey("karte.Karte", on_delete=models.CASCADE, related_name="drafts", null=True, blank=True)
    inbound_message = models.ForeignKey("lineapp.InboundMessage", on_delete=models.CASCADE, related_name="reply_drafts", null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    body = models.TextField("本文")
    generated_body = models.TextField("AI生成時の本文", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    scheduled_for = models.DateField("送信予定日", null=True, blank=True)
    tracked_link = models.ForeignKey("lineapp.TrackedLink", on_delete=models.SET_NULL, null=True, blank=True, related_name="drafts")
    sent_at = models.DateTimeField(null=True, blank=True)
    meta = models.JSONField(default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "下書き"
        verbose_name_plural = "下書き"

    def __str__(self):
        return f"{self.get_kind_display()} → {self.customer or '-'}"

    @property
    def is_sendable_status(self) -> bool:
        return self.status in (self.Status.DRAFT, self.Status.APPROVED)

    @property
    def is_edited(self) -> bool:
        return bool(self.generated_body) and self.generated_body != self.body


class SnsPost(TimeStampedModel):
    class Purpose(models.TextChoices):
        NOMINATION = "nomination", "指名を増やしたい"
        WEEKDAY_DAYTIME = "weekday_daytime", "平日昼を埋めたい"
        FIRST_TIMER = "first_timer", "初めての人の不安を減らす"
        REPEAT = "repeat", "再来店につなげる"
        GENERAL = "general", "特に決めない"

    class Status(models.TextChoices):
        GENERATING = "generating", "生成中"
        DRAFT = "draft", "下書き"
        POSTED = "posted", "投稿済み"
        DISCARDED = "discarded", "破棄"
        FAILED = "failed", "失敗"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="sns_posts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="sns_posts")
    karte = models.ForeignKey("karte.Karte", on_delete=models.SET_NULL, null=True, blank=True, related_name="sns_posts")
    purpose = models.CharField("投稿の目的", max_length=20, choices=Purpose.choices, default=Purpose.GENERAL)
    uses_story = models.BooleanField("悩み・ストーリーを使う", default=False)
    generalized_story = models.JSONField("一般化した悩みと結果", default=dict, blank=True)
    episode = models.ForeignKey("profiles.Episode", on_delete=models.SET_NULL, null=True, blank=True, related_name="sns_posts")
    photos = models.ManyToManyField("karte.KartePhoto", blank=True, related_name="sns_posts")
    extra_notes = models.CharField("補足", max_length=300, blank=True)

    feed_text = models.TextField("フィード投稿文", blank=True)
    story_text = models.TextField("ストーリーズ用", blank=True)
    reel_script = models.TextField("リール台本", blank=True)
    hashtags = models.JSONField(default=list, blank=True)
    pii_check = models.JSONField("個人情報チェック結果", default=dict, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    error = models.TextField(blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "SNS投稿"
        verbose_name_plural = "SNS投稿"

    def __str__(self):
        return f"SNS {self.get_purpose_display()} ({self.get_status_display()})"

    @property
    def hashtags_text(self) -> str:
        return " ".join(self.hashtags or [])

    @property
    def pii_passed(self) -> bool:
        return bool(self.pii_check) and self.pii_check.get("passed", False)

    @property
    def pii_errors(self) -> list[dict]:
        return [f for f in (self.pii_check or {}).get("findings", []) if f.get("severity") == "error"]

    @property
    def pii_warnings(self) -> list[dict]:
        return [f for f in (self.pii_check or {}).get("findings", []) if f.get("severity") == "warning"]

    @property
    def is_processing(self) -> bool:
        return self.status == self.Status.GENERATING
