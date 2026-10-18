import uuid
from pathlib import Path

from django.db import models

from apps.core.models import TenantManager, TimeStampedModel


def memo_audio_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".webm"
    return f"stylist_{instance.stylist_id}/memos/{uuid.uuid4().hex}{ext}"


def karte_photo_path(instance, filename):
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"stylist_{instance.karte.stylist_id}/photos/{uuid.uuid4().hex}{ext}"


class VoiceMemo(TimeStampedModel):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "受付"
        TRANSCRIBING = "transcribing", "文字起こし中"
        STRUCTURING = "structuring", "カルテ作成中"
        GENERATING = "generating", "文面作成中"
        DONE = "done", "完了"
        FAILED = "failed", "失敗"

    PROCESSING_STATUSES = [Status.UPLOADED, Status.TRANSCRIBING, Status.STRUCTURING, Status.GENERATING]

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="voice_memos")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="voice_memos")
    visit = models.ForeignKey("visits.Visit", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_memos")
    visited_on = models.DateField("来店日")
    audio = models.FileField("音声", upload_to=memo_audio_path, blank=True, null=True)
    audio_mime = models.CharField(max_length=50, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    text_input = models.TextField("テキスト入力", blank=True)
    transcript = models.TextField("文字起こし", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    error = models.TextField(blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "音声メモ"
        verbose_name_plural = "音声メモ"

    def __str__(self):
        return f"{self.customer} {self.visited_on} ({self.get_status_display()})"

    @property
    def is_processing(self) -> bool:
        return self.status in self.PROCESSING_STATUSES

    @property
    def progress_percent(self) -> int:
        return {
            self.Status.UPLOADED: 10,
            self.Status.TRANSCRIBING: 35,
            self.Status.STRUCTURING: 65,
            self.Status.GENERATING: 85,
            self.Status.DONE: 100,
            self.Status.FAILED: 100,
        }.get(self.status, 0)


class Karte(TimeStampedModel):
    """簡易カルテ。private_notes など公開NG情報を含むので、SNS生成には直接渡さない。"""

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="kartes")
    customer = models.ForeignKey("customers.Customer", on_delete=models.CASCADE, related_name="kartes")
    visit = models.ForeignKey("visits.Visit", on_delete=models.SET_NULL, null=True, blank=True, related_name="kartes")
    memo = models.OneToOneField(VoiceMemo, on_delete=models.SET_NULL, null=True, blank=True, related_name="karte")
    visited_on = models.DateField("来店日")

    treatment_summary = models.TextField("施術内容", blank=True)
    menu_items = models.JSONField("メニュー", default=list, blank=True)
    design_details = models.TextField("仕上がりの詳細", blank=True)
    concerns = models.JSONField("お悩み", default=list, blank=True)
    results = models.TextField("悩みへの対処・結果", blank=True)
    products_used = models.JSONField("使用剤・商品", default=list, blank=True)
    home_care_advice = models.JSONField("ホームケア", default=list, blank=True)
    next_check_items = models.JSONField("次回確認事項", default=list, blank=True)
    next_visit_weeks = models.PositiveSmallIntegerField("次回来店目安(週)", null=True, blank=True)
    customer_requests = models.JSONField("お客様の要望", default=list, blank=True)
    permission_mentions = models.JSONField("メモ内の掲載許可の言及", default=dict, blank=True)
    private_notes = models.TextField("非公開メモ", blank=True)
    raw_json = models.JSONField(default=dict, blank=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-visited_on", "-created_at"]
        verbose_name = "カルテ"
        verbose_name_plural = "カルテ"

    def __str__(self):
        return f"{self.customer} {self.visited_on}"

    def menu_display(self) -> str:
        return "・".join(self.menu_items or []) or "—"

    def as_prompt_dict(self) -> dict:
        """LINE文面生成用（本人宛てなので個別情報を含めてよいが、private_notes は除外）。"""
        return {
            "treatment_summary": self.treatment_summary,
            "menu_items": self.menu_items,
            "design_details": self.design_details,
            "concerns": self.concerns,
            "results": self.results,
            "products_used": self.products_used,
            "home_care_advice": self.home_care_advice,
            "next_check_items": self.next_check_items,
            "next_visit_weeks": self.next_visit_weeks,
            "customer_requests": self.customer_requests,
        }

    def sns_safe_fields(self) -> dict:
        """SNS生成に渡してよい項目だけを返す（ホワイトリスト）。"""
        return {
            "concerns": list(self.concerns or []),
            "results": self.results or "",
            "treatment_summary": self.treatment_summary or "",
            "design_details": self.design_details or "",
            "menu_items": list(self.menu_items or []),
        }

    def consent_suggestions(self) -> list[dict]:
        """メモで言及された掲載許可と、顧客設定の差分を返す。"""
        mentions = self.permission_mentions or {}
        labels = {"photo_ok": "施術写真の掲載", "face_ok": "顔出し", "story_ok": "悩み・ストーリーの掲載"}
        out = []
        for field, label in labels.items():
            value = mentions.get(field)
            if value is None:
                continue
            current = getattr(self.customer, field)
            if bool(value) != bool(current):
                out.append({"field": field, "label": label, "value": bool(value)})
        return out


class KartePhoto(TimeStampedModel):
    karte = models.ForeignKey(Karte, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField("写真", upload_to=karte_photo_path)
    sns_ok = models.BooleanField("この写真はSNS掲載OK", default=True)
    face_visible = models.BooleanField("顔が写っている", default=False)
    role = models.CharField("ビフォー／アフター", max_length=8, choices=[("after", "アフター"), ("before", "ビフォー")], default="after")
    caption = models.CharField("メモ", max_length=100, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "施術写真"
        verbose_name_plural = "施術写真"

    def usable_for_sns(self) -> bool:
        customer = self.karte.customer
        if not (self.sns_ok and customer.photo_ok):
            return False
        if self.face_visible and not customer.face_ok:
            return False
        return True

    def blocked_reason(self) -> str:
        customer = self.karte.customer
        if not customer.photo_ok:
            return "お客様が写真掲載NG"
        if not self.sns_ok:
            return "この写真は掲載しない設定"
        if self.face_visible and not customer.face_ok:
            return "顔出しNG（顔が写っている）"
        return ""
