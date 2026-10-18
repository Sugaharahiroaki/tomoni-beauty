"""SNS動画投稿（リール）のデータ。

流れ：型を選ぶ（カルテから写真を取り込める）→ 撮影リストに沿って撮る → 台本（Claude）→ 確認・修正
      → 動画作成（FFmpeg・Gemini TTS）→ 確認 → 予約投稿（Instagram / YouTube ショート / Threads）
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

from .fields import SecretTextField
from .recipes import TEMPLATE_KEYS, TEMPLATE_LABELS

POST_STATUSES = [
    ("DRAFT", "撮影中"),
    ("SCRIPTING", "台本づくり中"),
    ("REVIEW", "台本の確認待ち"),
    ("RENDERING", "動画を作成中"),
    ("READY", "動画の確認待ち"),
    ("SCHEDULED", "予約済み"),
    ("PUBLISHED", "公開済み"),
    ("FAILED", "失敗"),
]


def upload_to(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    stylist_id = getattr(instance, "stylist_id", None) or instance.post.stylist_id
    return f"stylist_{stylist_id}/reels/{uuid.uuid4().hex}.{ext}"


class ReelProfile(TimeStampedModel):
    """美容師のSNS動画の設定（ブランド・声・投稿先）"""

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, primary_key=True, related_name="reel_profile")
    brand_name = models.CharField("動画に出す名前（サロン名か美容師名）", max_length=100, blank=True)
    default_cta = models.CharField("いつもの呼びかけ", max_length=100, blank=True, default="ご相談はDMかプロフィールから")
    posts_per_month = models.PositiveSmallIntegerField("月の投稿本数の目安", default=8)
    ai_label = models.BooleanField("AI音声の表示を付ける", default=True)

    narration_mode = models.CharField("ナレーション", max_length=10, default="ai", choices=[("ai", "AIの声"), ("own", "本人の声で録音"), ("none", "声なし（テロップとBGMだけ）")])
    voice_name = models.CharField("声", max_length=40, default="Sulafat")
    speaker_gender = models.CharField("話し手の性別", max_length=5, default="女性", choices=[("女性", "女性"), ("男性", "男性")])
    speaker_age = models.CharField("話し手の年代", max_length=10, blank=True, default="30代")

    instagram_business_id = models.CharField(max_length=40, blank=True)
    instagram_username = models.CharField(max_length=100, blank=True)
    instagram_access_token = SecretTextField(blank=True)
    instagram_token_expires_at = models.DateTimeField(null=True, blank=True)
    youtube_channel_id = models.CharField(max_length=40, blank=True)
    youtube_channel_title = models.CharField(max_length=100, blank=True)
    youtube_refresh_token = SecretTextField(blank=True)
    threads_user_id = models.CharField(max_length=40, blank=True)
    threads_username = models.CharField(max_length=100, blank=True)
    threads_access_token = SecretTextField(blank=True)
    threads_token_expires_at = models.DateTimeField(null=True, blank=True)
    post_to_instagram = models.BooleanField("Instagramリールに投稿", default=True)
    post_to_youtube = models.BooleanField("YouTubeショートに投稿", default=False)
    post_to_threads = models.BooleanField("Threadsに投稿", default=False)

    class Meta:
        verbose_name = verbose_name_plural = "SNS動画の設定"

    def __str__(self):
        return f"{self.stylist} のSNS動画設定"

    @property
    def instagram_connected(self) -> bool:
        return bool(self.instagram_business_id and self.instagram_access_token)

    @property
    def youtube_connected(self) -> bool:
        return bool(self.youtube_refresh_token)

    @property
    def threads_connected(self) -> bool:
        return bool(self.threads_user_id and self.threads_access_token)

    def display_name(self) -> str:
        return self.brand_name or self.stylist.salon_name or self.stylist.display_name


class BgmTrack(TimeStampedModel):
    """BGMライブラリ（運営が登録。商用利用の条件を確認した曲だけ本番で使う）"""

    CATEGORIES = ["bright", "daily", "acoustic", "calm", "emotional", "lofi"]
    CATEGORY_LABELS = {"bright": "明るい", "daily": "日常", "acoustic": "アコースティック", "calm": "落ち着いた", "emotional": "しんみり", "lofi": "ローファイ"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField("曲名", max_length=100)
    file = models.FileField("音源", upload_to="bgm/")
    category = models.CharField("カテゴリ", max_length=12, choices=[(c, c) for c in CATEGORIES])
    mood = models.CharField("雰囲気", max_length=50, blank=True)
    duration_sec = models.FloatField("長さ（秒）", default=0)
    level_duck = models.FloatField(null=True, blank=True)
    level_base = models.FloatField(null=True, blank=True)
    source_url = models.URLField("入手元", blank=True)
    license_note = models.TextField("ライセンスのメモ", blank=True)
    license_confirmed = models.BooleanField("商用利用の条件を確認した", default=False)
    active = models.BooleanField("使う", default=True)
    used_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "BGM"
        ordering = ["category", "title"]

    def __str__(self):
        return f"[{self.category}] {self.title}"

    @classmethod
    def usable(cls):
        tracks = cls.objects.filter(active=True)
        return tracks.filter(license_confirmed=True) if settings.BGM_REQUIRE_LICENSE else tracks

    @property
    def category_label(self) -> str:
        return self.CATEGORY_LABELS.get(self.category, self.category)


class ReelPost(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="reel_posts")
    karte = models.ForeignKey("karte.Karte", on_delete=models.SET_NULL, null=True, blank=True, related_name="reel_posts")
    customer = models.ForeignKey("customers.Customer", on_delete=models.SET_NULL, null=True, blank=True, related_name="reel_posts")
    template_key = models.CharField("型", max_length=20, choices=[(k, TEMPLATE_LABELS[k]) for k in TEMPLATE_KEYS])
    menu_items = models.JSONField("今日の施術", default=list, blank=True)
    status = models.CharField("状態", max_length=12, choices=POST_STATUSES, default="DRAFT")
    theme_title = models.CharField("テーマ", max_length=100, blank=True)
    shot_list = models.JSONField("撮影リスト", default=list, blank=True)
    script = models.JSONField("台本", null=True, blank=True)
    episode_ids = models.JSONField("使ったエピソード", default=list, blank=True)
    uses_story = models.BooleanField("お客様の悩みと結果を使う", default=False)
    generalized_story = models.JSONField("一般化した悩みと結果", default=dict, blank=True)
    face_allowed = models.BooleanField("顔が写った素材を使ってよい", default=False)
    bgm = models.ForeignKey(BgmTrack, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    narration_mode = models.CharField(max_length=10, default="ai")
    ai_label = models.BooleanField("AI音声の表示", default=True)
    notes = models.JSONField("作成時のメモ", default=list, blank=True)
    pii_check = models.JSONField("個人情報チェック", default=dict, blank=True)

    ig_caption = models.TextField("Instagramのキャプション", blank=True)
    hashtags = models.JSONField("ハッシュタグ", default=list, blank=True)
    yt_title = models.CharField("YouTubeのタイトル", max_length=100, blank=True)
    yt_description = models.TextField("YouTubeの説明", blank=True)

    video = models.FileField(upload_to=upload_to, blank=True)
    thumbnail = models.ImageField(upload_to=upload_to, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    render_count = models.PositiveIntegerField(default=0)

    scheduled_at = models.DateTimeField("投稿の予定日時", null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    publish_result = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "SNS動画投稿"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.theme_title or self.template_label} ({self.get_status_display()})"

    @property
    def template_label(self) -> str:
        return TEMPLATE_LABELS.get(self.template_key, self.template_key)

    @property
    def is_busy(self) -> bool:
        return self.status in ("SCRIPTING", "RENDERING")

    @property
    def step(self) -> int:
        return {"DRAFT": 0, "SCRIPTING": 0, "REVIEW": 1, "RENDERING": 2, "READY": 2, "FAILED": 2, "SCHEDULED": 3, "PUBLISHED": 4}.get(self.status, 0)

    @property
    def pii_errors(self) -> list:
        return [f for f in (self.pii_check or {}).get("findings", []) if f.get("severity") == "error"]

    def usable_assets(self):
        qs = self.assets.all()
        return qs if self.face_allowed else qs.filter(face_visible=False)


class MediaAsset(TimeStampedModel):
    """撮影した写真・動画（またはカルテから取り込んだ写真）"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(ReelPost, on_delete=models.CASCADE, related_name="assets")
    file = models.FileField(upload_to=upload_to)
    kind = models.CharField(max_length=5, choices=[("photo", "写真"), ("video", "動画")])
    mime = models.CharField(max_length=50)
    bytes = models.PositiveBigIntegerField(default=0)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration_sec = models.FloatField(null=True, blank=True)
    slot = models.CharField("撮影リストのどの項目か", max_length=40, blank=True)
    order_index = models.PositiveSmallIntegerField(default=0)
    taken_at = models.DateTimeField(null=True, blank=True)
    face_visible = models.BooleanField("顔が写っている", default=False)
    analysis = models.JSONField(default=dict, blank=True)
    best_start = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=10, default="own", choices=[("own", "撮影"), ("karte", "カルテの写真")])
    karte_photo = models.ForeignKey("karte.KartePhoto", on_delete=models.SET_NULL, null=True, blank=True, related_name="reel_assets")

    class Meta:
        verbose_name = verbose_name_plural = "動画の素材"
        ordering = ["order_index", "created_at"]

    @property
    def stylist_id(self):
        return self.post.stylist_id

    @property
    def poster_path(self):
        a = self.analysis or {}
        if a.get("poster_name"):
            return self.file.storage.path(a["poster_name"])
        return None

    @property
    def poster_url(self):
        if self.kind == "video":
            return (self.analysis or {}).get("poster_url") or ""
        return self.file.url if self.file else ""


class NarrationTake(TimeStampedModel):
    post = models.ForeignKey(ReelPost, on_delete=models.CASCADE, related_name="takes")
    scene_index = models.PositiveSmallIntegerField()
    file = models.FileField(upload_to=upload_to)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "scene_index"], name="reel_take_per_scene")]

    @property
    def stylist_id(self):
        return self.post.stylist_id


class RenderJob(TimeStampedModel):
    STATUSES = [("queued", "待ち"), ("running", "作成中"), ("done", "完成"), ("failed", "失敗")]

    post = models.ForeignKey(ReelPost, on_delete=models.CASCADE, related_name="render_jobs")
    status = models.CharField(max_length=10, choices=STATUSES, default="queued")
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True)
    log = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]


class PostMetric(models.Model):
    post = models.ForeignKey(ReelPost, on_delete=models.CASCADE, related_name="metrics")
    platform = models.CharField(max_length=20, choices=[("instagram", "Instagram"), ("youtube", "YouTube"), ("threads", "Threads")])
    views = models.PositiveBigIntegerField(null=True, blank=True)
    reach = models.PositiveBigIntegerField(null=True, blank=True)
    likes = models.PositiveBigIntegerField(null=True, blank=True)
    comments = models.PositiveBigIntegerField(null=True, blank=True)
    shares = models.PositiveBigIntegerField(null=True, blank=True)
    saves = models.PositiveBigIntegerField(null=True, blank=True)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fetched_at"]

    @property
    def platform_label(self) -> str:
        return dict(self._meta.get_field("platform").choices).get(self.platform, self.platform)


class UsageLog(models.Model):
    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="ai_usage_logs")
    post = models.ForeignKey(ReelPost, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    provider = models.CharField(max_length=20)
    model = models.CharField(max_length=50, blank=True)
    operation = models.CharField(max_length=40)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    audio_seconds = models.FloatField(default=0)
    cost_usd = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ShotExample(TimeStampedModel):
    """撮影リストの見本写真（運営が管理画面で登録）"""

    template_key = models.CharField("型", max_length=20, choices=[(k, TEMPLATE_LABELS[k]) for k in TEMPLATE_KEYS])
    slot_key = models.CharField("項目", max_length=40)
    image = models.ImageField("見本", upload_to="examples/")
    note = models.CharField("ひとこと", max_length=100, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["template_key", "slot_key"]
