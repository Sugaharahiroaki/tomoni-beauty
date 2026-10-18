import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.core.dates import year_month
from apps.core.models import TenantManager, TimeStampedModel

from .quota import QuotaStatus


def generate_webhook_key() -> str:
    return secrets.token_urlsafe(32)


def generate_link_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "a").replace("_", "b")[:8]


class LineChannel(TimeStampedModel):
    """美容師個人の LINE 公式アカウント（Messaging API チャネル）。"""

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, related_name="line_channel")
    channel_id = models.CharField("チャネルID", max_length=32, blank=True)
    channel_secret = models.CharField("チャネルシークレット", max_length=64)
    channel_access_token = models.TextField("チャネルアクセストークン（長期）")
    bot_user_id = models.CharField("ボットのユーザーID (U…)", max_length=64, blank=True)
    basic_id = models.CharField("ベーシックID (@…)", max_length=32, blank=True)
    display_name = models.CharField("アカウント名", max_length=100, blank=True)
    webhook_key = models.CharField(max_length=64, unique=True, default=generate_webhook_key)
    push_enabled = models.BooleanField(
        "Push送信を使う（有料プラン向け・通数を消費）",
        default=False,
        help_text="オフのままなら、通数を消費しない「コピーしてLINEで送る」とReply返信のみ使います",
    )
    chat_url_template = models.CharField(
        "チャット画面URLテンプレート（上級者向け）",
        max_length=300,
        blank=True,
        help_text="空欄なら既定値。{bot_user_id} {line_user_id} が使えます",
    )
    is_verified = models.BooleanField("接続確認済み", default=False)
    last_verified_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "LINEチャネル"
        verbose_name_plural = "LINEチャネル"

    def __str__(self):
        return f"{self.stylist} LINE ({self.basic_id or self.channel_id or '未確認'})"

    @property
    def webhook_url(self) -> str:
        return f"{settings.SITE_URL}{reverse('lineapp:webhook', kwargs={'key': self.webhook_key})}"

    def chat_url_for(self, customer) -> str | None:
        """美容師が LINE Official Account Manager の該当トークを開くURL。"""
        if not self.bot_user_id:
            return None
        if customer is not None and customer.line_user_id:
            template = self.chat_url_template or settings.LINE_CHAT_URL_TEMPLATE
            return template.format(bot_user_id=self.bot_user_id, line_user_id=customer.line_user_id)
        return settings.LINE_CHAT_LIST_URL_TEMPLATE.format(bot_user_id=self.bot_user_id)

    def current_quota(self):
        return self.quota_usages.filter(year_month=year_month(timezone.localdate())).first()

    def quota_summary(self) -> dict | None:
        usage = self.current_quota()
        if usage is None:
            return None
        return QuotaStatus(limit=usage.quota_limit, used=usage.total_usage).to_dict(settings.LINE_QUOTA_WARN_RATIO) | {"fetched_at": usage.fetched_at}


class InboundMessage(TimeStampedModel):
    """お客様から届いたメッセージ（Webhook）。"""

    class SuggestionStatus(models.TextChoices):
        PENDING = "pending", "返信案を作成中"
        DONE = "done", "返信案あり"
        FAILED = "failed", "返信案の作成に失敗"
        NONE = "none", "対象外"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="inbound_messages")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="inbound_messages")
    line_message_id = models.CharField(max_length=64, blank=True)
    message_type = models.CharField(max_length=20, default="text")
    text = models.TextField(blank=True)
    reply_token = models.CharField(max_length=128, blank=True)
    reply_token_used = models.BooleanField(default=False)
    received_at = models.DateTimeField()
    raw_event = models.JSONField(default=dict, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    reply_route = models.CharField(max_length=10, blank=True)
    ignored = models.BooleanField("対応不要", default=False)
    suggestion_status = models.CharField(max_length=10, choices=SuggestionStatus.choices, default=SuggestionStatus.PENDING)
    intent = models.CharField(max_length=20, blank=True)
    needs_attention = models.BooleanField(default=False)
    note_for_stylist = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "受信メッセージ"
        verbose_name_plural = "受信メッセージ"

    def __str__(self):
        return f"{self.customer}: {self.text[:30]}"

    def reply_token_expires_at(self):
        return self.received_at + timedelta(seconds=settings.LINE_REPLY_TOKEN_TTL_SECONDS)

    def reply_token_valid(self, now=None) -> bool:
        if not self.reply_token or self.reply_token_used:
            return False
        now = now or timezone.now()
        return now < self.reply_token_expires_at()

    def reply_token_seconds_left(self, now=None) -> int:
        now = now or timezone.now()
        return max(int((self.reply_token_expires_at() - now).total_seconds()), 0)

    @property
    def latest_reply_draft(self):
        return self.reply_drafts.exclude(status="discarded").order_by("-created_at").first()

    @property
    def display_text(self) -> str:
        if self.message_type == "text":
            return self.text
        return {"image": "［画像］", "sticker": "［スタンプ］", "video": "［動画］", "audio": "［音声］", "location": "［位置情報］", "file": "［ファイル］"}.get(self.message_type, "［メッセージ］")


class TrackedLink(models.Model):
    """ホットペッパー予約URLへのクリック計測付きリダイレクト。"""

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="tracked_links")
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="tracked_links")
    code = models.CharField(max_length=12, unique=True, default=generate_link_code)
    target_url = models.URLField(max_length=500)
    kind = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.code

    @property
    def url(self) -> str:
        return f"{settings.SITE_URL}{reverse('lineapp:link_redirect', kwargs={'code': self.code})}"

    @property
    def click_count(self) -> int:
        return self.clicks.count()


class LinkClick(models.Model):
    link = models.ForeignKey(TrackedLink, on_delete=models.CASCADE, related_name="clicks")
    clicked_at = models.DateTimeField(auto_now_add=True)
    user_agent = models.CharField(max_length=300, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["-clicked_at"]


class Message(TimeStampedModel):
    """美容師 → お客様 への送信ログ。ルートごとに通数消費の有無が異なる。"""

    class Route(models.TextChoices):
        COPY = "copy", "コピーしてLINEチャットで送信（無料）"
        REPLY = "reply", "Reply API（無料）"
        PUSH = "push", "Push API（通数を消費）"

    class Kind(models.TextChoices):
        THANKS_CARE = "thanks_care", "お礼＋お手入れ案内"
        NEXT_VISIT = "next_visit", "次回案内"
        REPLY = "reply", "返信"
        CUSTOM = "custom", "その他"
        BROADCAST = "broadcast", "一斉配信"

    class Status(models.TextChoices):
        SENT = "sent", "送信済み"
        FAILED = "failed", "失敗"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="messages")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="messages", null=True, blank=True)
    draft = models.ForeignKey("drafts.Draft", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.CUSTOM)
    route = models.CharField(max_length=10, choices=Route.choices)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField()
    error = models.TextField(blank=True)
    tracked_link = models.ForeignKey(TrackedLink, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    line_response = models.JSONField(default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "送信メッセージ"
        verbose_name_plural = "送信メッセージ"

    def __str__(self):
        return f"{self.get_kind_display()} → {self.customer} ({self.get_route_display()})"

    @property
    def consumed_quota(self) -> bool:
        return self.route == self.Route.PUSH


class QuotaUsage(models.Model):
    channel = models.ForeignKey(LineChannel, on_delete=models.CASCADE, related_name="quota_usages")
    year_month = models.CharField(max_length=7)
    quota_type = models.CharField(max_length=10, blank=True)  # none | limited
    quota_limit = models.PositiveIntegerField(null=True, blank=True)
    total_usage = models.PositiveIntegerField(default=0)
    local_push_count = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("channel", "year_month")]
        ordering = ["-year_month"]

    def __str__(self):
        return f"{self.channel} {self.year_month}: {self.total_usage}/{self.quota_limit or '∞'}"

    def status(self, planned: int = 0) -> QuotaStatus:
        return QuotaStatus(limit=self.quota_limit, used=self.total_usage, planned=planned)
