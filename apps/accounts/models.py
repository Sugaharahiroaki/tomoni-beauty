from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


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
    weekly_slot_hours = models.DecimalField("週の稼働時間(h)", max_digits=5, decimal_places=1, null=True, blank=True)
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

    def ensure_email_import_key(self) -> str:
        if not self.email_import_key:
            import secrets

            self.email_import_key = secrets.token_urlsafe(24)
            self.save(update_fields=["email_import_key", "updated_at"])
        return self.email_import_key
