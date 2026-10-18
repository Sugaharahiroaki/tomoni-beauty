from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import MenuItem, Stylist, User


class SignupForm(forms.Form):
    name = forms.CharField(label="お名前（表示名）", max_length=100)
    email = forms.EmailField(label="メールアドレス")
    password1 = forms.CharField(label="パスワード", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="パスワード（確認）", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    agree = forms.BooleanField(label="利用規約とプライバシーポリシーに同意する")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("このメールアドレスは既に登録されています")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "パスワードが一致しません")
        if p1:
            password_validation.validate_password(p1)
        return cleaned

    def save(self) -> User:
        user = User.objects.create_user(
            email=self.cleaned_data["email"], password=self.cleaned_data["password1"], name=self.cleaned_data["name"]
        )
        Stylist.objects.create(user=user, display_name=self.cleaned_data["name"])
        return user


class LoginForm(AuthenticationForm):
    username = forms.EmailField(label="メールアドレス", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))


WEEKDAY_CHOICES = [(0, "月"), (1, "火"), (2, "水"), (3, "木"), (4, "金"), (5, "土"), (6, "日")]


class StylistBasicForm(forms.ModelForm):
    hotpepper_url = forms.URLField(
        label="ホットペッパー予約URL",
        required=False,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=...&stylistId="}),
        help_text="スタイリスト指名予約ページのURL（例: https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=H000000000&stylistId=T000000000）",
    )
    work_days = forms.MultipleChoiceField(label="働く曜日", choices=WEEKDAY_CHOICES, required=False, widget=forms.CheckboxSelectMultiple, help_text="空き枠は「稼働時間 − 予約」で自動で出します")
    work_start = forms.TimeField(label="稼働の開始", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))
    work_end = forms.TimeField(label="稼働の終了", required=False, widget=forms.TimeInput(attrs={"type": "time"}, format="%H:%M"))

    class Meta:
        model = Stylist
        fields = [
            "display_name",
            "salon_name",
            "hotpepper_url",
            "salon_access",
            "commission_rate",
            "nominated_commission_rate",
            "expense_rate",
            "avg_price",
            "weekly_slot_hours",
            "avg_service_minutes",
            "default_cycle_weeks",
            "follow_up_lead_days",
            "max_broadcasts_per_month",
            "broadcast_min_interval_days",
        ]
        widgets = {
            "commission_rate": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
            "nominated_commission_rate": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
            "expense_rate": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
            "avg_price": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "weekly_slot_hours": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst = self.instance
        if inst is not None and inst.pk:
            self.fields["work_days"].initial = [str(d) for d in (inst.work_days or [])]
            self.fields["work_start"].initial = inst.work_start
            self.fields["work_end"].initial = inst.work_end

    def clean(self):
        cd = super().clean()
        start, end = cd.get("work_start"), cd.get("work_end")
        if start and end and end <= start:
            self.add_error("work_end", "稼働の終了は開始より後にしてください")
        return cd

    def save(self, commit=True):
        stylist = super().save(commit=False)
        days = self.cleaned_data.get("work_days")
        if days:
            stylist.work_days = sorted(int(d) for d in days)
        if self.cleaned_data.get("work_start"):
            stylist.work_start = self.cleaned_data["work_start"]
        if self.cleaned_data.get("work_end"):
            stylist.work_end = self.cleaned_data["work_end"]
        if commit:
            stylist.save()
        return stylist

    def clean_hotpepper_url(self):
        url = (self.cleaned_data.get("hotpepper_url") or "").strip()
        if url and "hotpepper.jp" not in url:
            raise forms.ValidationError("ホットペッパービューティーのURL（beauty.hotpepper.jp）を入力してください")
        return url


class AccountDeleteForm(forms.Form):
    confirm = forms.CharField(label="確認のため「削除」と入力", max_length=10)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("confirm") != "削除":
            self.add_error("confirm", "「削除」と入力してください")
        if cleaned.get("password") and not self.user.check_password(cleaned["password"]):
            self.add_error("password", "パスワードが違います")
        return cleaned


class MenuItemForm(forms.ModelForm):
    class Meta:
        model = MenuItem
        fields = ["category", "name", "price", "price_from", "target", "minutes", "duration_weeks", "note", "is_active", "order"]
        widgets = {
            "price": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "minutes": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "order": forms.NumberInput(attrs={"inputmode": "numeric"}),
        }


class MenuBulkForm(forms.Form):
    text = forms.CharField(
        label="まとめて追加（1行に1メニュー）",
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "カット+透明感カラー 6500\n【再来】似合わせカット+ナチュラルカラー ¥5,900\nブリーチカラー 7,000円〜"}),
        help_text="ホットペッパーのクーポン名と料金をそのまま貼り付けられます。【新規】【再来】が付いていれば対象も自動で設定します。",
    )
