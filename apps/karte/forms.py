from django import forms

from .models import Karte, KartePhoto


class LinesField(forms.CharField):
    """改行区切りのテキスト ⇄ JSON配列。"""

    widget = forms.Textarea(attrs={"rows": 3})

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("required", False)
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(value)
        return value

    def to_python(self, value):
        text = super().to_python(value) or ""
        return [line.strip() for line in text.splitlines() if line.strip()]


class KarteForm(forms.ModelForm):
    menu_items = LinesField(label="メニュー（1行に1つ）")
    concerns = LinesField(label="お悩み（1行に1つ）")
    home_care_advice = LinesField(label="ホームケア（1行に1つ）")
    next_check_items = LinesField(label="次回確認事項（1行に1つ）")
    products_used = LinesField(label="使用剤・商品（1行に1つ）")

    class Meta:
        model = Karte
        fields = [
            "visited_on",
            "treatment_summary",
            "menu_items",
            "design_details",
            "concerns",
            "results",
            "products_used",
            "home_care_advice",
            "next_check_items",
            "next_visit_weeks",
            "private_notes",
        ]
        widgets = {
            "visited_on": forms.DateInput(attrs={"type": "date"}),
            "treatment_summary": forms.Textarea(attrs={"rows": 2}),
            "design_details": forms.Textarea(attrs={"rows": 2}),
            "results": forms.Textarea(attrs={"rows": 2}),
            "private_notes": forms.Textarea(attrs={"rows": 3}),
            "next_visit_weeks": forms.NumberInput(attrs={"inputmode": "numeric", "min": 1, "max": 52}),
        }


class KartePhotoForm(forms.ModelForm):
    class Meta:
        model = KartePhoto
        fields = ["image", "sns_ok", "face_visible", "role", "caption"]
