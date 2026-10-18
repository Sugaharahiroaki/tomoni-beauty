from django.apps import AppConfig


class BroadcastsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.broadcasts"
    verbose_name = "一斉配信・空き枠・リッチメニュー"

    def ready(self):
        from . import signals  # noqa: F401  予約の変更で空き枠を自動更新
