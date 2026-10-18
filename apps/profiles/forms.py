from django import forms

from .models import Episode, StylistProfile


class StyleForm(forms.ModelForm):
    class Meta:
        model = StylistProfile
        fields = ["first_person", "tone", "emoji_level", "ng_words", "signature", "sample_text", "style_summary", "area_tags"]
        widgets = {
            "tone": forms.TextInput(attrs={"placeholder": "例: やわらかい丁寧語。「〜かなと思います」が多め"}),
            "sample_text": forms.Textarea(attrs={"rows": 5, "placeholder": "過去のInstagram投稿やLINE文面を2〜3件貼り付け"}),
            "style_summary": forms.Textarea(attrs={"rows": 3}),
        }


class EpisodeForm(forms.ModelForm):
    themes_text = forms.CharField(label="テーマタグ", required=False, help_text="カンマ区切り（例: カラー, 修業時代, 価値観）")

    class Meta:
        model = Episode
        fields = ["title", "body", "is_active"]
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["themes_text"].initial = ", ".join(self.instance.themes or [])

    def save(self, commit=True):
        obj = super().save(commit=False)
        raw = self.cleaned_data.get("themes_text") or ""
        obj.themes = [t.strip() for t in raw.replace("、", ",").split(",") if t.strip()][:8]
        if commit:
            obj.save()
        return obj


class InterviewTextForm(forms.Form):
    transcript = forms.CharField(label="回答（テキスト）", widget=forms.Textarea(attrs={"rows": 5}), required=False)
