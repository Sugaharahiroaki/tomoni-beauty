"""SNS投稿のデータ（動画・フィード・ストーリーズを1つの流れで扱う）。

流れ：素材を入れる（写真・動画・カルテの写真）→ 型を決める（AIのおすすめ／自分で）→ フックを選ぶ
      → 出来上がり（動画＝台本→FFmpeg→Gemini TTS／フィード・ストーリーズ＝文章）→ 投稿（予約投稿 or コピー）
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel

from .fields import SecretTextField
from .post_types import FORMATS, HOOK_TYPE_LABELS, PURPOSES, ROLES, TYPE_CHOICES, TYPE_LABELS
from .recipes import TEMPLATE_KEYS, TEMPLATE_LABELS

POST_STATUSES = [
    ("DRAFT", "作業中"),
    ("HOOKING", "フックを考え中"),
    ("SCRIPTING", "台本づくり中"),
    ("REVIEW", "台本の確認待ち"),
    ("RENDERING", "動画を作成中"),
    ("READY", "出来上がり"),
    ("SCHEDULED", "予約済み"),
    ("PUBLISHED", "公開済み"),
    ("FAILED", "失敗"),
    ("SKIPPED", "スキップ"),
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
    posts_per_week = models.PositiveSmallIntegerField("週の投稿本数の目安", default=2)
    # 投稿の軸（テーマは一貫させ、見せ方＝型を変える）
    focus_concerns = models.JSONField("得意な悩み（1〜3個）", default=list, blank=True)
    purpose = models.CharField("投稿の目的", max_length=20, choices=PURPOSES, default="nomination")
    favorite_types = models.JSONField("よく使う型", default=list, blank=True)
    avoid_types = models.JSONField("避けたい型", default=list, blank=True)
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
        verbose_name = verbose_name_plural = "SNS投稿の設定"

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

    @property
    def purpose_label(self) -> str:
        return dict(PURPOSES).get(self.purpose, self.purpose)


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
    post_type = models.CharField("型", max_length=20, choices=TYPE_CHOICES, blank=True)
    template_key = models.CharField("動画の構成", max_length=20, choices=[(k, TEMPLATE_LABELS[k]) for k in TEMPLATE_KEYS], blank=True)
    output_format = models.CharField("出来上がる形", max_length=10, choices=FORMATS, default="reel")
    selection_mode = models.CharField("型の選び方", max_length=10, choices=[("manual", "自分で選んだ"), ("ai", "AIのおすすめ")], blank=True)
    theme = models.CharField("テーマ（得意な悩み）", max_length=100, blank=True)
    hooks = models.JSONField("フック案", default=list, blank=True)
    hook_regenerations = models.PositiveSmallIntegerField("フックを作り直した回数", default=0)
    selected_hook = models.JSONField("選んだフック", default=dict, blank=True)
    carousel = models.JSONField("フィード各枚の文字", default=list, blank=True)
    stories = models.JSONField("ストーリーズ", default=list, blank=True)
    cover_text = models.CharField("表紙の文字", max_length=60, blank=True)
    caption_check = models.JSONField("キャプションの6要素", default=dict, blank=True)
    hype_check = models.JSONField("誇大表現チェック", default=dict, blank=True)
    tracked_link = models.ForeignKey("lineapp.TrackedLink", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    # 成果（手入力・空欄可）
    m_saves = models.PositiveIntegerField("保存数", null=True, blank=True)
    m_profile_visits = models.PositiveIntegerField("プロフィールアクセス", null=True, blank=True)
    m_link_clicks = models.PositiveIntegerField("予約リンククリック", null=True, blank=True)
    m_dms = models.PositiveIntegerField("DM", null=True, blank=True)
    m_new_customers = models.PositiveIntegerField("インスタ経由の新規", null=True, blank=True)
    metrics_note = models.CharField("成果のメモ", max_length=200, blank=True)
    metrics_updated_at = models.DateTimeField(null=True, blank=True)
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
        verbose_name = verbose_name_plural = "SNS投稿"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.theme_title or self.type_label} ({self.get_status_display()})"

    @property
    def template_label(self) -> str:
        return TEMPLATE_LABELS.get(self.template_key, self.template_key)

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.post_type) or self.template_label or "投稿"

    @property
    def format_label(self) -> str:
        return dict(FORMATS).get(self.output_format, self.output_format)

    @property
    def hook_type_label(self) -> str:
        return HOOK_TYPE_LABELS.get((self.selected_hook or {}).get("type", ""), "")

    @property
    def is_busy(self) -> bool:
        return self.status in ("HOOKING", "SCRIPTING", "RENDERING")

    @property
    def is_done(self) -> bool:
        return self.status in ("READY", "SCHEDULED", "PUBLISHED", "FAILED", "SKIPPED")

    @property
    def stage(self) -> int:
        """4ステップ（素材／型／フック／出来上がり）のどこか"""
        if self.status in ("READY", "SCHEDULED", "PUBLISHED", "FAILED", "SKIPPED", "RENDERING", "REVIEW", "SCRIPTING"):
            return 3
        if self.status == "HOOKING" or (self.post_type and self.hooks):
            return 2
        if self.post_type:
            return 2 if self.hooks else 1
        return 0

    @property
    def hype_errors(self) -> list:
        return [f for f in (self.hype_check or {}).get("findings", []) if f.get("severity") == "error"]

    @property
    def telops(self) -> list[str]:
        if self.script:
            return [s.get("caption", "") for s in self.script.get("scenes", []) if s.get("caption")]
        return [s.get("title") or s.get("text", "") for s in (self.carousel or [])]

    @property
    def manual_result_score(self) -> float | None:
        """成果のまとめ（予約リンククリック×3＋DM×3＋新規×5＋プロフィール×1＋保存×0.5）"""
        if self.metrics_updated_at is None:
            return None
        return (self.m_link_clicks or 0) * 3 + (self.m_dms or 0) * 3 + (self.m_new_customers or 0) * 5 + (self.m_profile_visits or 0) + (self.m_saves or 0) * 0.5

    @property
    def recommendation(self):
        return self.recommendations.order_by("-created_at").first()

    def get_workspace_url(self) -> str:
        from django.urls import reverse

        return reverse("reels:workspace", kwargs={"pk": self.pk})

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
    role = models.CharField("役割", max_length=10, choices=ROLES, blank=True)
    order_index = models.PositiveSmallIntegerField(default=0)
    taken_at = models.DateTimeField(null=True, blank=True)
    face_visible = models.BooleanField("顔が写っている", default=False)
    analysis = models.JSONField(default=dict, blank=True)
    best_start = models.FloatField(null=True, blank=True)
    source = models.CharField(max_length=10, default="own", choices=[("own", "撮影"), ("karte", "カルテの写真"), ("library", "前に撮ったもの"), ("stock", "ネットの素材")])
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

    @property
    def role_label(self) -> str:
        return dict(ROLES).get(self.role, "未設定")

    @property
    def is_stock(self) -> bool:
        return self.source == "stock"

    @property
    def credit(self) -> str:
        return (self.analysis or {}).get("credit", "")


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


class TypeRecommendation(TimeStampedModel):
    """AIおまかせの提案と、美容師の反応（採用／変更／スキップ）の記録"""

    REACTIONS = [("pending", "未回答"), ("accepted", "採用"), ("changed", "変更"), ("skipped", "スキップ")]

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="type_recommendations")
    post = models.ForeignKey(ReelPost, on_delete=models.SET_NULL, null=True, blank=True, related_name="recommendations")
    post_type = models.CharField("提案した型", max_length=20, choices=TYPE_CHOICES)
    alternatives = models.JSONField("次点", default=list, blank=True)
    scores = models.JSONField("スコアの内訳", default=dict, blank=True)
    reason = models.TextField("理由", blank=True)
    missing = models.JSONField("足りない素材", default=dict, blank=True)
    context = models.JSONField("計算に使った材料", default=dict, blank=True)
    reaction = models.CharField("反応", max_length=10, choices=REACTIONS, default="pending")
    changed_to = models.CharField("変更先の型", max_length=20, blank=True)
    reacted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = verbose_name_plural = "型の提案"

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.post_type, self.post_type)

    def react(self, reaction: str, changed_to: str = "") -> None:
        self.reaction, self.changed_to, self.reacted_at = reaction, changed_to, timezone.now()
        self.save(update_fields=["reaction", "changed_to", "reacted_at", "updated_at"])
