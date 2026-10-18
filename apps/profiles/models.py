from django.db import models

from apps.core.models import TenantManager, TimeStampedModel


def interview_audio_path(instance, filename):
    return f"stylist_{instance.stylist_id}/interview/q{instance.question.order}_{filename}"


class StylistProfile(TimeStampedModel):
    """文体設定とインタビュー由来のまとめ。Episode は別テーブル。"""

    stylist = models.OneToOneField("accounts.Stylist", on_delete=models.CASCADE, related_name="profile")
    first_person = models.CharField("一人称", max_length=10, default="私")
    tone = models.CharField("語尾・トーン", max_length=200, blank=True, help_text="例: やわらかい丁寧語。「〜かなと思います」が多め")
    emoji_level = models.PositiveSmallIntegerField("絵文字の量", default=1, choices=[(0, "使わない"), (1, "少し"), (2, "普通"), (3, "多め")])
    ng_words = models.CharField("使わない言葉", max_length=200, blank=True, help_text="カンマ区切り")
    signature = models.CharField("LINEの署名", max_length=100, blank=True)
    sample_text = models.TextField("参考にする自分の文章", blank=True, help_text="過去の投稿やLINE文面を貼ると文体の再現度が上がります")
    style_summary = models.TextField("話し方の特徴（AI生成・編集可）", blank=True)
    area_tags = models.CharField("地域ハッシュタグ", max_length=200, blank=True, help_text="例: #渋谷美容室, #表参道ヘアサロン（カンマ区切り）")

    class Meta:
        verbose_name = "プロフィール"
        verbose_name_plural = "プロフィール"

    def __str__(self):
        return f"{self.stylist} のプロフィール"

    def as_style_dict(self) -> dict:
        return {
            "first_person": self.first_person,
            "tone": self.tone,
            "emoji_level": self.emoji_level,
            "ng_words": self.ng_words,
            "signature": self.signature,
            "sample_text": self.sample_text,
            "style_summary": self.style_summary,
        }

    def area_tag_list(self) -> list[str]:
        tags = []
        for raw in self.area_tags.replace("、", ",").split(","):
            t = raw.strip()
            if t:
                tags.append(t if t.startswith("#") else f"#{t}")
        return tags


class InterviewQuestion(models.Model):
    order = models.PositiveSmallIntegerField("順番", unique=True)
    text = models.CharField("質問", max_length=300)
    hint = models.CharField("答え方のヒント", max_length=300, blank=True)
    theme = models.CharField("テーマ", max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "インタビュー質問"
        verbose_name_plural = "インタビュー質問"

    def __str__(self):
        return f"Q{self.order}. {self.text}"


class InterviewAnswer(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "未処理"
        TRANSCRIBING = "transcribing", "文字起こし中"
        DONE = "done", "完了"
        FAILED = "failed", "失敗"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="interview_answers")
    question = models.ForeignKey(InterviewQuestion, on_delete=models.CASCADE, related_name="answers")
    audio = models.FileField("音声", upload_to=interview_audio_path, blank=True, null=True)
    transcript = models.TextField("文字起こし／回答", blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)

    objects = TenantManager()

    class Meta:
        unique_together = [("stylist", "question")]
        ordering = ["question__order"]

    def __str__(self):
        return f"{self.stylist} Q{self.question.order}"


class Episode(TimeStampedModel):
    class Source(models.TextChoices):
        AI = "ai", "インタビューから生成"
        MANUAL = "manual", "手入力"

    stylist = models.ForeignKey("accounts.Stylist", on_delete=models.CASCADE, related_name="episodes")
    title = models.CharField("タイトル", max_length=100)
    body = models.TextField("エピソード本文")
    themes = models.JSONField("テーマタグ", default=list, blank=True)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    source_answer = models.ForeignKey(InterviewAnswer, on_delete=models.SET_NULL, null=True, blank=True, related_name="episodes")
    is_active = models.BooleanField("投稿に使う", default=True)

    objects = TenantManager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "人柄エピソード"
        verbose_name_plural = "人柄エピソード"

    def __str__(self):
        return self.title

    def themes_display(self) -> str:
        return "、".join(self.themes or [])

    def as_prompt_dict(self) -> dict:
        return {"title": self.title, "body": self.body, "themes": self.themes}


class EpisodeUsage(models.Model):
    """どの投稿でどのエピソードを使ったか（同じ話の連続使用を防ぐ）。"""

    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="usages")
    sns_post = models.ForeignKey("drafts.SnsPost", on_delete=models.CASCADE, related_name="episode_usages", null=True, blank=True)
    used_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-used_at"]
