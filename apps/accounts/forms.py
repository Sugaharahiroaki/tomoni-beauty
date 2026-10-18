from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import Stylist, User


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


class StylistBasicForm(forms.ModelForm):
    hotpepper_url = forms.URLField(
        label="ホットペッパー予約URL",
        required=False,
        assume_scheme="https",
        widget=forms.URLInput(attrs={"placeholder": "https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=...&stylistId="}),
        help_text="スタイリスト指名予約ページのURL（例: https://beauty.hotpepper.jp/CSP/bt/reserve/?storeId=H000000000&stylistId=T000000000）",
    )

    class Meta:
        model = Stylist
        fields = [
            "display_name",
            "salon_name",
            "hotpepper_url",
            "commission_rate",
            "avg_price",
            "weekly_slot_hours",
            "default_cycle_weeks",
            "follow_up_lead_days",
        ]
        widgets = {
            "commission_rate": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
            "avg_price": forms.NumberInput(attrs={"inputmode": "numeric"}),
            "weekly_slot_hours": forms.NumberInput(attrs={"inputmode": "decimal", "step": "0.5"}),
        }

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
