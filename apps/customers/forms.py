from django import forms

from .models import Customer, Tag


class CustomerForm(forms.ModelForm):
    tags_text = forms.CharField(label="タグ", required=False, help_text="カンマ区切り（例: カラー, 平日昼, 常連）")

    class Meta:
        model = Customer
        fields = ["name", "kana", "call_name", "contact_ok", "photo_ok", "face_ok", "story_ok", "preferred_timing", "memo"]
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "山田 花子"}),
            "kana": forms.TextInput(attrs={"autocomplete": "off", "placeholder": "やまだ はなこ"}),
            "call_name": forms.TextInput(attrs={"placeholder": "山田さん"}),
            "memo": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, stylist=None, **kwargs):
        self.stylist = stylist
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["tags_text"].initial = ", ".join(self.instance.tags.values_list("name", flat=True))

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.stylist_id is None and self.stylist is not None:
            obj.stylist = self.stylist
        consent_fields = {"contact_ok", "photo_ok", "face_ok", "story_ok"}
        if any(f in self.changed_data for f in consent_fields):
            obj.record_consent_change()
        obj.needs_review = False
        if commit:
            obj.save()
            names = [t.strip() for t in (self.cleaned_data.get("tags_text") or "").replace("、", ",").split(",") if t.strip()]
            tags = [Tag.objects.get_or_create(stylist=obj.stylist, name=n[:30])[0] for n in names]
            obj.tags.set(tags)
        return obj


class QuickCustomerForm(forms.Form):
    """録音画面から新規顧客を即作成するための最小フォーム。"""

    name = forms.CharField(label="お名前", max_length=100)


class LinkLineForm(forms.Form):
    """LINE友だち（自動作成された顧客）を既存顧客に紐付ける。"""

    target = forms.ModelChoiceField(label="紐付ける既存のお客様", queryset=Customer.objects.none())

    def __init__(self, *args, stylist=None, exclude_pk=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Customer.objects.filter(stylist=stylist, line_user_id__isnull=True)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        self.fields["target"].queryset = qs.order_by("name")
