from django import forms

from .models import LineChannel


class LineChannelForm(forms.ModelForm):
    class Meta:
        model = LineChannel
        fields = ["channel_id", "channel_secret", "channel_access_token", "push_enabled", "chat_url_template"]
        labels = {"chat_url_template": "チャット画面URLテンプレート（上級者向け）"}
        widgets = {
            "channel_secret": forms.TextInput(attrs={"autocomplete": "off"}),
            "channel_access_token": forms.Textarea(attrs={"rows": 3, "autocomplete": "off"}),
        }
        help_texts = {
            "channel_id": "LINE Developers › Messaging API チャネル › チャネル基本設定",
            "channel_secret": "同じ画面の「チャネルシークレット」",
            "channel_access_token": "Messaging API設定タブ › チャネルアクセストークン（長期）を発行して貼り付け",
        }
