from django import forms

from apps.customers.models import Customer, Tag

from .models import AvailabilitySlot, Broadcast, RichMenu, WaitlistEntry


class BroadcastForm(forms.ModelForm):
    tags = forms.MultipleChoiceField(label="タグで絞り込む", required=False, widget=forms.CheckboxSelectMultiple)
    last_visit_min_days = forms.IntegerField(label="最終来店から○日以上", required=False, min_value=1, widget=forms.NumberInput(attrs={"inputmode": "numeric", "placeholder": "例: 60"}))
    last_visit_max_days = forms.IntegerField(label="最終来店から○日以内", required=False, min_value=1, widget=forms.NumberInput(attrs={"inputmode": "numeric"}))
    include_never_visited = forms.BooleanField(label="来店記録のない友だちも含める", required=False)
    preferred_timing = forms.CharField(label="希望時期に含む言葉", required=False, widget=forms.TextInput(attrs={"placeholder": "例: 平日昼"}))
    menu_keyword = forms.CharField(label="過去メニューに含む言葉", required=False, widget=forms.TextInput(attrs={"placeholder": "例: カラー"}))
    exclude_recent_days = forms.IntegerField(label="直近○日に配信した人を除く", required=False, min_value=0, initial=30)
    exclude_reserved = forms.BooleanField(label="予約済みの人を除く", required=False, initial=True)
    waitlist_only = forms.BooleanField(label="キャンセル待ち登録者のみ", required=False)
    slots = forms.ModelMultipleChoiceField(label="案内する空き枠", queryset=AvailabilitySlot.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    ai_notes = forms.CharField(label="伝えたい内容（AIで下書きするときのメモ）", required=False, widget=forms.Textarea(attrs={"rows": 2, "placeholder": "例: 11/3は休業。新しいトリートメント導入。"}))

    class Meta:
        model = Broadcast
        fields = ["kind", "title", "body"]
        widgets = {"kind": forms.RadioSelect, "body": forms.Textarea(attrs={"rows": 8, "placeholder": "AIで下書きを作るか、ここに直接入力。予約リンクを入れたい場所に {予約リンク} と書くと計測リンクに置き換わります"})}

    def __init__(self, *args, stylist=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stylist = stylist
        self.fields["tags"].choices = [(t.name, t.name) for t in Tag.objects.filter(stylist=stylist)]
        self.fields["slots"].queryset = AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN).order_by("date", "start_time")
        self.fields["body"].required = False
        seg = (self.instance.segment or {}) if self.instance and self.instance.pk else {}
        for key in ("tags", "last_visit_min_days", "last_visit_max_days", "include_never_visited", "preferred_timing", "menu_keyword", "exclude_recent_days", "exclude_reserved", "waitlist_only"):
            if key in seg:
                self.fields[key].initial = seg[key]

    def segment_dict(self) -> dict:
        cd = self.cleaned_data
        return {
            "tags": cd.get("tags") or [],
            "last_visit_min_days": cd.get("last_visit_min_days"),
            "last_visit_max_days": cd.get("last_visit_max_days"),
            "include_never_visited": bool(cd.get("include_never_visited")),
            "preferred_timing": cd.get("preferred_timing") or "",
            "menu_keyword": cd.get("menu_keyword") or "",
            "exclude_recent_days": cd.get("exclude_recent_days") if cd.get("exclude_recent_days") is not None else 30,
            "exclude_reserved": bool(cd.get("exclude_reserved")),
            "waitlist_only": bool(cd.get("waitlist_only")),
        }

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.stylist = self.stylist
        obj.segment = self.segment_dict()
        if commit:
            obj.save()
            obj.slots.set(self.cleaned_data.get("slots") or [])
        return obj


class AvailabilitySlotForm(forms.ModelForm):
    class Meta:
        model = AvailabilitySlot
        fields = ["date", "start_time", "end_time", "note"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start_time") and cleaned.get("end_time") and cleaned["end_time"] <= cleaned["start_time"]:
            raise forms.ValidationError("終了時刻は開始より後にしてください")
        return cleaned


class WaitlistForm(forms.ModelForm):
    class Meta:
        model = WaitlistEntry
        fields = ["customer", "preferred_timing", "note"]

    def __init__(self, *args, stylist=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(stylist=stylist).order_by("name")


class RichMenuForm(forms.ModelForm):
    class Meta:
        model = RichMenu
        fields = ["reserve_label", "consult_label", "waitlist_label", "consult_message", "waitlist_reply", "auto_reply_enabled", "chat_bar_text", "image"]
        widgets = {"waitlist_reply": forms.Textarea(attrs={"rows": 3})}
