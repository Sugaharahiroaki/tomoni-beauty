from django import forms

from apps.profiles.models import Episode

from .models import SnsPost


class SnsPostForm(forms.Form):
    purpose = forms.ChoiceField(label="投稿の目的", choices=SnsPost.Purpose.choices, widget=forms.RadioSelect, initial=SnsPost.Purpose.GENERAL)
    uses_story = forms.BooleanField(label="お客様の「悩みと結果」を使う（一般化して掲載）", required=False)
    episode = forms.ModelChoiceField(label="織り込むエピソード", queryset=Episode.objects.none(), required=False, empty_label="（自動で選ぶ）")
    no_episode = forms.BooleanField(label="エピソードを使わない", required=False)
    photos = forms.MultipleChoiceField(label="使う写真", required=False, widget=forms.CheckboxSelectMultiple)
    extra_notes = forms.CharField(label="補足（任意）", max_length=300, required=False, widget=forms.TextInput(attrs={"placeholder": "例: 今週は水曜の午後が空いています"}))

    def __init__(self, *args, stylist=None, karte=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.karte = karte
        self.fields["episode"].queryset = Episode.objects.filter(stylist=stylist, is_active=True).order_by("title")
        usable = [p for p in karte.photos.all() if p.usable_for_sns()] if karte else []
        self.fields["photos"].choices = [(str(p.id), p.caption or f"写真 {p.id}") for p in usable]
        self.usable_photos = usable
        if karte and not karte.customer.story_ok:
            self.fields["uses_story"].disabled = True
            self.fields["uses_story"].help_text = "このお客様はストーリー掲載NGのため、施術内容のみで作成します"
        elif karte:
            self.fields["uses_story"].initial = True
