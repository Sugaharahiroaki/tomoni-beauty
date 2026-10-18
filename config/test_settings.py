"""テスト用設定: 外部API・ワーカーを使わない。"""
from .settings import *  # noqa: F401,F403

DEBUG = False
AI_FAKE = True
TRANSCRIPTION_FAKE = True
Q_CLUSTER = {**Q_CLUSTER, "sync": True}  # noqa: F405
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
SITE_URL = "https://app.example.test"
WHITENOISE_AUTOREFRESH = True
WHITENOISE_USE_FINDERS = True
SIGNUP_ENABLED = True
DELETE_AUDIO_AFTER_TRANSCRIPTION = False
SECURE_SSL_REDIRECT = False
INTERNAL_API_TOKEN = "test-internal-token"
