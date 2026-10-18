from django import forms

from .engine.tts import VOICES
from .models import ReelProfile
from .recipes import TEMPLATES


class ReelProfileForm(forms.ModelForm):
    voice_name = forms.ChoiceField(label="声", choices=[(v["name"], f"{v['gender']}・{v['feature']}") for v in VOICES])

    class Meta:
        model = ReelProfile
        fields = ["brand_name", "default_cta", "posts_per_month", "narration_mode", "voice_name", "speaker_gender", "speaker_age", "ai_label", "post_to_instagram", "post_to_youtube", "post_to_threads"]
        widgets = {"narration_mode": forms.RadioSelect}


class StartForm(forms.Form):
    template_key = forms.ChoiceField(label="投稿の型", choices=[(k, t["label"]) for k, t in TEMPLATES.items()] + [("", "おまかせ")], required=False, widget=forms.RadioSelect)
    menu_items = forms.CharField(label="今日の施術（カンマ区切り）", required=False, widget=forms.TextInput(attrs={"placeholder": "例: カラー, トリートメント"}))
    uses_story = forms.BooleanField(label="お客様の「悩みと結果」を使う（ストーリー掲載OKのお客様のみ・一般化して使用）", required=False)
    import_photos = forms.BooleanField(label="カルテの写真（掲載OKのもの）を素材として取り込む", required=False, initial=True)

    def clean_menu_items(self):
        raw = self.cleaned_data.get("menu_items") or ""
        return [m.strip() for m in raw.replace("、", ",").split(",") if m.strip()][:6]
