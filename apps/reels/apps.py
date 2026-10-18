from django.apps import AppConfig


class ReelsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reels"
    verbose_name = "SNS動画投稿"

    def ready(self):
        from . import signals  # noqa: F401
