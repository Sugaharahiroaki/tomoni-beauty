from django import forms

from .engine.tts import VOICES
from .models import ReelProfile
from .post_types import TYPE_CHOICES


class ReelProfileForm(forms.ModelForm):
    """SNS投稿の設定：投稿の軸（得意な悩み・目的・型の好み・週の本数）＋ 動画の設定（名前・声・投稿先）"""

    focus_concerns_text = forms.CharField(
        label="得意な悩み（1行に1つ、1〜3個）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "例: ブリーチ後の色落ち・黄ばみ\n伸びた根元の境目\nくせ・広がり"}),
        help_text="投稿のテーマはここから選びます。見せ方（型）は変えても、テーマは一貫させて「この悩みならこの人」と覚えてもらいます。",
    )
    favorite_types = forms.MultipleChoiceField(label="よく使う型", choices=TYPE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple)
    avoid_types = forms.MultipleChoiceField(label="避けたい型", choices=TYPE_CHOICES, required=False, widget=forms.CheckboxSelectMultiple, help_text="おすすめの候補から外します（自分で選ぶことはできます）")
    voice_name = forms.ChoiceField(label="声", choices=[(v["name"], f"{v['gender']}・{v['feature']}") for v in VOICES])

    FOCUS_FIELDS = ["focus_concerns_text", "purpose", "favorite_types", "avoid_types", "posts_per_week"]
    VIDEO_FIELDS = ["brand_name", "default_cta", "narration_mode", "voice_name", "speaker_gender", "speaker_age", "ai_label", "post_to_instagram", "post_to_youtube", "post_to_threads"]

    class Meta:
        model = ReelProfile
        fields = ["purpose", "posts_per_week", "brand_name", "default_cta", "narration_mode", "voice_name", "speaker_gender", "speaker_age", "ai_label", "post_to_instagram", "post_to_youtube", "post_to_threads"]
        widgets = {"narration_mode": forms.RadioSelect, "posts_per_week": forms.NumberInput(attrs={"inputmode": "numeric", "min": 0, "max": 14})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst and inst.pk:
            self.fields["focus_concerns_text"].initial = "\n".join(inst.focus_concerns or [])
            self.fields["favorite_types"].initial = list(inst.favorite_types or [])
            self.fields["avoid_types"].initial = list(inst.avoid_types or [])

    def clean_focus_concerns_text(self):
        lines = [ln.strip() for ln in (self.cleaned_data.get("focus_concerns_text") or "").splitlines() if ln.strip()]
        return lines[:3]

    def clean(self):
        cd = super().clean()
        both = set(cd.get("favorite_types") or []) & set(cd.get("avoid_types") or [])
        if both:
            self.add_error("avoid_types", "「よく使う型」と「避けたい型」に同じ型は入れられません")
        return cd

    def save(self, commit=True):
        profile = super().save(commit=False)
        profile.focus_concerns = self.cleaned_data.get("focus_concerns_text") or []
        profile.favorite_types = list(self.cleaned_data.get("favorite_types") or [])
        profile.avoid_types = list(self.cleaned_data.get("avoid_types") or [])
        if commit:
            profile.save()
        return profile

    def focus_fields(self):
        return [self[name] for name in self.FOCUS_FIELDS]

    def video_fields(self):
        return [self[name] for name in self.VIDEO_FIELDS]
