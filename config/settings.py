"""
Django settings for TOMONI Beauty.

すべての秘密情報・環境依存値は環境変数（.env）から読む。.env.example を参照。
"""
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key, default):
    value = os.environ.get(key)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def env_list(key, default=""):
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# 外部から到達できるURL（LINE本文に埋める予約リンクなどに使う）
SITE_URL = env("SITE_URL", "http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_q",
    "apps.core",
    "apps.accounts",
    "apps.ai",
    "apps.profiles",
    "apps.customers",
    "apps.visits",
    "apps.karte",
    "apps.drafts",
    "apps.lineapp",
    "apps.broadcasts",
    "apps.ledger",
    "apps.reels",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.StylistMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database  (DATABASE_URL=postgres://user:pass@host:5432/db  未設定ならSQLite)
# ---------------------------------------------------------------------------
def _database_from_url(url):
    if not url:
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
    parsed = urlparse(url)
    if parsed.scheme.startswith("postgres"):
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "localhost",
            "PORT": str(parsed.port or 5432),
            "CONN_MAX_AGE": 60,
        }
    if parsed.scheme.startswith("sqlite"):
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path or (BASE_DIR / "db.sqlite3")}
    raise ValueError("Unsupported DATABASE_URL scheme: %s" % parsed.scheme)


DATABASES = {"default": _database_from_url(env("DATABASE_URL"))}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:today"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static / Media
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"


def _static_version() -> str:
    """CSS/JS の更新時刻からバージョン文字列を作る（URL の ?v= とサービスワーカーのキャッシュ名に使う）。本番は STATIC_VERSION で固定も可"""
    paths = [BASE_DIR / "static" / "css" / "app.css", *sorted((BASE_DIR / "static" / "js").glob("*.js"))]
    return str(int(max((p.stat().st_mtime for p in paths if p.exists()), default=0)))


STATIC_VERSION = env("STATIC_VERSION", "") or _static_version()
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT") or (BASE_DIR / "media"))
# 音声・写真はスマホから直接上がるので上限を広めに（25MB）
DATA_UPLOAD_MAX_MEMORY_SIZE = 26 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 26 * 1024 * 1024

# ---------------------------------------------------------------------------
# Security（本番）
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30  # 施術の合間に使うので30日ログイン維持


# ---------------------------------------------------------------------------
# Background jobs (django-q2)  本番は manage.py qcluster を常駐させる
# ---------------------------------------------------------------------------
Q_CLUSTER = {
    "name": "tomoni",
    "workers": env_int("Q_WORKERS", 2),
    "timeout": 600,
    "retry": 700,
    "max_attempts": 2,
    "orm": "default",
    "sync": env_bool("Q_SYNC", DEBUG),  # 開発時は同期実行（ワーカー不要）
    "catch_up": False,
}

# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = env("CLAUDE_EFFORT", "medium")
# 安全分類器が拒否した場合に別モデルへ自動フォールバック（Claude API 側機能）
CLAUDE_FALLBACKS_ENABLED = env_bool("CLAUDE_FALLBACKS_ENABLED", True)

OPENAI_API_KEY = env("OPENAI_API_KEY", "")
TRANSCRIPTION_MODEL = env("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")

# APIキーが無い環境（開発・CI）はダミー実装で動かす
AI_FAKE = env_bool("AI_FAKE", not bool(ANTHROPIC_API_KEY))
TRANSCRIPTION_FAKE = env_bool("TRANSCRIPTION_FAKE", not bool(OPENAI_API_KEY))

# ---------------------------------------------------------------------------
# LINE
# ---------------------------------------------------------------------------
LINE_API_BASE = "https://api.line.me"
LINE_DATA_API_BASE = "https://api-data.line.me"
# Replyトークンの有効期限（LINE公式: Webhook受信から1分以内・1回限り）。余裕をみて50秒。
LINE_REPLY_TOKEN_TTL_SECONDS = env_int("LINE_REPLY_TOKEN_TTL_SECONDS", 50)
# LINE Official Account Manager のチャット画面URL（美容師側で開く）。
# {bot_user_id} = ボットのユーザーID(U...) / {line_user_id} = 顧客のユーザーID(U...)
LINE_CHAT_URL_TEMPLATE = env(
    "LINE_CHAT_URL_TEMPLATE", "https://chat.line.biz/{bot_user_id}/chat/{line_user_id}"
)
LINE_CHAT_LIST_URL_TEMPLATE = env("LINE_CHAT_LIST_URL_TEMPLATE", "https://chat.line.biz/{bot_user_id}")
LINE_FREE_PLAN_MONTHLY_LIMIT = env_int("LINE_FREE_PLAN_MONTHLY_LIMIT", 200)
LINE_QUOTA_WARN_RATIO = 0.8

# ---------------------------------------------------------------------------
# 業務ルール
# ---------------------------------------------------------------------------
# 「案内 → 予約」の帰属ウィンドウ（日）。案内送信後この日数以内の予約を効果として計測
ATTRIBUTION_WINDOW_DAYS = env_int("ATTRIBUTION_WINDOW_DAYS", 14)
# 同一顧客への同種案内の最短間隔（日）。連続送信の防止
MIN_DAYS_BETWEEN_SAME_KIND_MESSAGES = env_int("MIN_DAYS_BETWEEN_SAME_KIND_MESSAGES", 7)
# 次回フォロー案内を送るタイミング：推奨来店日の何日前か
FOLLOW_UP_LEAD_DAYS_DEFAULT = 7
DEFAULT_VISIT_CYCLE_WEEKS = 6

# n8n などから内部エンドポイントを叩くときのトークン
INTERNAL_API_TOKEN = env("INTERNAL_API_TOKEN", "")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"django.request": {"level": "WARNING"}, "apps": {"level": env("LOG_LEVEL", "INFO")}},
}

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"
WHITENOISE_AUTOREFRESH = DEBUG
WHITENOISE_USE_FINDERS = DEBUG

# 試験運用中は招待制にしたい場合 false にする（管理画面からユーザー作成）
SIGNUP_ENABLED = env_bool("SIGNUP_ENABLED", True)

# ---------------------------------------------------------------------------
# 一斉配信（第2段階）
# ---------------------------------------------------------------------------
# 同じお客様に一斉配信を重ねない既定の間隔（日）
BROADCAST_EXCLUDE_RECENT_DAYS_DEFAULT = env_int("BROADCAST_EXCLUDE_RECENT_DAYS_DEFAULT", 30)
# Multicast 1回あたりの宛先数（LINE上限は500）
LINE_MULTICAST_CHUNK = 150
# リッチメニュー画像に使う日本語フォント（無ければ候補を探索）
RICH_MENU_FONT_PATH = env("RICH_MENU_FONT_PATH", "")

# ---------------------------------------------------------------------------
# SNS動画投稿（リール）: 台本=Claude、ナレーション=Gemini TTS、投稿=Instagram/YouTube/Threads
# ---------------------------------------------------------------------------
GEMINI_API_KEY = env("GEMINI_API_KEY", "")
PEXELS_API_KEY = env("PEXELS_API_KEY", "")  # ネットの素材（B-roll）。無ければその機能だけ出ない
# SNS投稿の「AIおまかせ」（型の採点）の重み。環境変数 SNS_W_PURPOSE などで上書きできる
SNS_RECOMMEND_WEIGHTS = {k: float(env(f"SNS_W_{k.upper()}", v)) for k, v in {"purpose": 3.0, "bias": 4.0, "streak": 3.0, "availability": 2.0, "results": 2.0, "favorite": 1.0, "accept": 1.0, "skip": 1.5}.items()}
INSTAGRAM_APP_ID = env("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = env("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_GRAPH_VERSION = env("INSTAGRAM_GRAPH_VERSION", "v25.0")
YOUTUBE_CLIENT_ID = env("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = env("YOUTUBE_CLIENT_SECRET", "")
THREADS_APP_ID = env("THREADS_APP_ID", "")
THREADS_APP_SECRET = env("THREADS_APP_SECRET", "")
# Instagram・Threads が動画を取りに来る公開URL（既定: SITE_URL + /media）
PUBLIC_MEDIA_BASE_URL = env("PUBLIC_MEDIA_BASE_URL", f"{SITE_URL}/media")
# 動画を組み立てる途中のファイル（公開しない場所）
RENDER_WORK_DIR = Path(env("RENDER_WORK_DIR") or (BASE_DIR / "render_work"))
# 本番では「商用利用の条件を確認した」BGMだけを使う
BGM_REQUIRE_LICENSE = env_bool("BGM_REQUIRE_LICENSE", not DEBUG)
# よく見られる時間（予約投稿の「おすすめ」）
SOCIAL_BEST_HOURS = env("SOCIAL_BEST_HOURS", "12,19")
# /media/ を Django で認証したあと Nginx に送り出させる（X-Accel-Redirect）。false なら Django が直接返す
MEDIA_ACCEL_REDIRECT = env_bool("MEDIA_ACCEL_REDIRECT", not DEBUG)

# ---------------------------------------------------------------------------
# 税務（第2・3段階）— すべて概算用の既定値。設定画面で美容師ごとに変更可
# ---------------------------------------------------------------------------
TAX_DEFAULTS = {
    "pension_monthly": env_int("TAX_PENSION_MONTHLY", 17920),  # 国民年金 月額（年度で変わる）
    "nhi_rate_pct": 11.0,  # 国民健康保険の概算料率（市区町村で異なる）
    "nhi_cap": env_int("TAX_NHI_CAP", 1090000),  # 国民健康保険の年間上限（概算）
    "resident_tax_rate_pct": 10.0,
    "resident_tax_flat": 5000,
    "resident_basic_deduction": 430000,
}
# 文字起こし完了後に音声ファイルを削除する（個人情報の保有を最小化）
DELETE_AUDIO_AFTER_TRANSCRIPTION = env_bool("DELETE_AUDIO_AFTER_TRANSCRIPTION", True)
