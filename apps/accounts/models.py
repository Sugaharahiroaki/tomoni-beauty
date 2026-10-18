from datetime import time
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


# 料金表に所要時間が無いときの、種類ごとの目安（分）
DEFAULT_CATEGORY_MINUTES = {"cut": 60, "color": 120, "bleach": 180, "perm": 120, "straight": 180, "treatment": 60, "spa": 45, "set": 150, "other": 60}


def all_weekdays() -> list[int]:
    return [0, 1, 2, 3, 4, 5, 6]


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("メールアドレスは必須です")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField("メールアドレス", unique=True)
    name = models.CharField("名前", max_length=100, blank=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "ユーザー"
        verbose_name_plural = "ユーザー"

    def __str__(self):
        return self.email

    def get_short_name(self):
        return self.name or self.email


class Stylist(models.Model):
    """美容師＝テナント。すべての業務データはこのモデルにぶら下がる。"""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stylist")
    display_name = models.CharField("表示名", max_length=100)
    salon_name = models.CharField("サロン名", max_length=100, blank=True)
    hotpepper_url = models.URLField(
        "ホットペッパー予約URL",
        blank=True,
        help_text="スタイリスト指名予約ページのURL（例: https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=H000000000&stylistId=T000000000）",
    )
    commission_rate = models.DecimalField("歩合率(%)", max_digits=5, decimal_places=2, null=True, blank=True)
    avg_price = models.PositiveIntegerField("平均客単価(円)", null=True, blank=True)
    nominated_commission_rate = models.DecimalField(
        "指名客の歩合率(%)", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="指名とフリーで歩合が違うときだけ入力。LINEや自分の予約リンクから来るお客様は指名扱いのことが多いです",
    )
    expense_rate = models.DecimalField(
        "歩合から引かれる諸経費(%)", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="例: 歩合から諸経費15%を引かれる場合は 15",
    )
    salon_access = models.CharField("サロンの場所（ひとこと）", max_length=60, blank=True, help_text="例: なんば駅から徒歩1分。SNS動画や投稿文で使います")
    weekly_slot_hours = models.DecimalField("週の稼働時間(h)", max_digits=5, decimal_places=1, null=True, blank=True)
    # 稼働時間（空き枠を「稼働時間 − 予約」で自動で出すのに使う）
    work_days = models.JSONField("働く曜日", default=all_weekdays, blank=True, help_text="0=月 … 6=日")
    work_start = models.TimeField("稼働の開始", default=time(10, 0))
    work_end = models.TimeField("稼働の終了", default=time(20, 0))
    category_minutes = models.JSONField("種類ごとの所要時間の目安(分)", default=dict, blank=True, help_text="料金表に無いメニューの予約の長さに使う")
    default_cycle_weeks = models.PositiveSmallIntegerField("標準の来店周期(週)", default=6)
    follow_up_lead_days = models.PositiveSmallIntegerField("次回案内を送る日数(来店目安の何日前)", default=7)
    avg_service_minutes = models.PositiveSmallIntegerField("1人あたりの平均施術時間(分)", default=90)

    # 一斉配信の頻度上限（ブロック防止・通数節約）
    max_broadcasts_per_month = models.PositiveSmallIntegerField("一斉配信の月間上限(回)", default=1)
    broadcast_min_interval_days = models.PositiveSmallIntegerField("一斉配信の最短間隔(日)", default=14)

    # 予約通知メール取り込み用のキー（n8n から送る際に美容師を特定）
    email_import_key = models.CharField(max_length=40, blank=True, default="", db_index=True)

    onboarding_completed = models.BooleanField("初期設定完了", default=False)
    interview_completed = models.BooleanField("インタビュー完了", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "美容師"
        verbose_name_plural = "美容師"

    def __str__(self):
        return self.display_name

    @property
    def has_hotpepper(self) -> bool:
        return bool(self.hotpepper_url)

    @property
    def line_ready(self) -> bool:
        channel = getattr(self, "line_channel", None)
        return bool(channel and channel.is_verified)

    def take_rate(self, nominated: bool = True) -> Decimal | None:
        """売上のうち手元に残る割合(%)。指名歩合があれば指名を使い、諸経費を差し引く"""
        rate = self.nominated_commission_rate if (nominated and self.nominated_commission_rate) else self.commission_rate
        if rate is None:
            return None
        rate = Decimal(rate)
        if self.expense_rate:
            rate = rate * (1 - Decimal(self.expense_rate) / 100)
        rate = rate.quantize(Decimal("0.01"))
        return rate.quantize(Decimal(1)) if rate == rate.to_integral_value() else rate.normalize()

    def take_rate_note(self) -> str:
        """「指名65% − 諸経費15%」のような内訳"""
        def pct(value) -> str:
            d = Decimal(value)
            return str(d.quantize(Decimal(1)) if d == d.to_integral_value() else d.normalize())

        parts = []
        if self.nominated_commission_rate:
            parts.append(f"指名{pct(self.nominated_commission_rate)}%")
        elif self.commission_rate is not None:
            parts.append(f"歩合{pct(self.commission_rate)}%")
        if self.expense_rate:
            parts.append(f"諸経費{pct(self.expense_rate)}%")
        return " − ".join(parts)

    def minutes_for_category(self, category: str) -> int | None:
        """種類ごとの所要時間（設定が無ければ既定値）"""
        value = (self.category_minutes or {}).get(category)
        try:
            return int(value) if value else DEFAULT_CATEGORY_MINUTES.get(category)
        except (TypeError, ValueError):
            return DEFAULT_CATEGORY_MINUTES.get(category)

    def menu_prompt_text(self, limit: int = 40) -> str:
        """AIに渡すメニュー・料金表（登録が無ければ空文字）"""
        items = list(self.menus.filter(is_active=True)[:limit])
        return "\n".join(f"- {m.label()}" for m in items)

    def ensure_email_import_key(self) -> str:
        if not self.email_import_key:
            import secrets

            self.email_import_key = secrets.token_urlsafe(24)
            self.save(update_fields=["email_import_key", "updated_at"])
        return self.email_import_key


class MenuItem(models.Model):
    """美容師のメニュー・料金表。LINE文面・返信案・告知文で料金に触れるときの唯一の根拠にする"""

    class Category(models.TextChoices):
        CUT = "cut", "カット"
        COLOR = "color", "カラー"
        BLEACH = "bleach", "ブリーチ・デザインカラー"
        PERM = "perm", "パーマ"
        STRAIGHT = "straight", "縮毛矯正"
        TREATMENT = "treatment", "トリートメント・髪質改善"
        SPA = "spa", "ヘッドスパ"
        SET = "set", "セットメニュー"
        OTHER = "other", "その他"

    class Target(models.TextChoices):
        ALL = "all", "全員"
        NEW = "new", "新規"
        REPEAT = "repeat", "再来"

    stylist = models.ForeignKey(Stylist, on_delete=models.CASCADE, related_name="menus")
    category = models.CharField("種類", max_length=20, choices=Category.choices, default=Category.OTHER)
    name = models.CharField("メニュー名", max_length=120)
    price = models.PositiveIntegerField("料金(円・税込)", null=True, blank=True)
    price_from = models.BooleanField("「〜」をつける", default=False, help_text="長さや髪の状態で変わる料金")
    target = models.CharField("対象", max_length=10, choices=Target.choices, default=Target.ALL)
    minutes = models.PositiveSmallIntegerField("所要時間(分)", null=True, blank=True)
    duration_weeks = models.PositiveSmallIntegerField("持ちの目安(週)", null=True, blank=True, help_text="SNSのキャプションの「持ち」に使います")
    note = models.CharField("補足", max_length=200, blank=True, help_text="例: 21時以降は+1,000円")
    is_active = models.BooleanField("使う", default=True)
    order = models.PositiveSmallIntegerField("並び順", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "メニュー・料金"
        verbose_name_plural = "メニュー・料金"
        ordering = ["order", "id"]

    def __str__(self):
        return self.label()

    def price_text(self) -> str:
        if self.price is None:
            return "料金は要相談"
        return f"{self.price:,}円{'〜' if self.price_from else ''}"

    def label(self) -> str:
        text = f"{self.name} {self.price_text()}"
        if self.target != self.Target.ALL:
            text += f"（{self.get_target_display()}）"
        if self.minutes:
            text += f"・約{self.minutes}分"
        if self.duration_weeks:
            text += f"・持ち約{self.duration_weeks}週間"
        if self.note:
            text += f"／{self.note}"
        return text
