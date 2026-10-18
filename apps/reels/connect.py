"""Instagram・YouTube・Threads のアカウントをつなぐ（OAuth）。

流れ：「つなぐ」→ 同意画面 → /reels/connect/<投稿先>/callback/ に戻る → コードをトークンに換えて暗号化保存。
つなぐ先のアプリ設定に「戻り先のURL」＝ {SITE_URL}/reels/connect/<投稿先>/callback/ を登録しておく。
"""
from __future__ import annotations

import logging
import urllib.parse
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core import signing
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.decorators import stylist_required

from .publishing import TH_GRAPH, PublishError, _http, ig_graph

log = logging.getLogger(__name__)

SALT = "reels-connect"
IG_SCOPES = ["instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"]
YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
TH_SCOPES = ["threads_basic", "threads_content_publish", "threads_manage_insights"]
PLATFORMS = ("instagram", "youtube", "threads")
LABELS = {"instagram": "Instagram", "youtube": "YouTube", "threads": "Threads"}


def available() -> dict:
    return {
        "instagram": bool(settings.INSTAGRAM_APP_ID and settings.INSTAGRAM_APP_SECRET),
        "youtube": bool(settings.YOUTUBE_CLIENT_ID and settings.YOUTUBE_CLIENT_SECRET),
        "threads": bool(settings.THREADS_APP_ID and settings.THREADS_APP_SECRET),
    }


def redirect_uri(platform: str) -> str:
    return f"{settings.SITE_URL}{reverse('reels:connect_callback', kwargs={'platform': platform})}"


def authorize_url(platform: str, state: str) -> str:
    if platform == "instagram":
        return "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({"client_id": settings.INSTAGRAM_APP_ID, "redirect_uri": redirect_uri(platform), "response_type": "code", "scope": ",".join(IG_SCOPES), "state": state})
    if platform == "threads":
        return "https://threads.com/oauth/authorize?" + urllib.parse.urlencode({"client_id": settings.THREADS_APP_ID, "redirect_uri": redirect_uri(platform), "response_type": "code", "scope": ",".join(TH_SCOPES), "state": state})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({"client_id": settings.YOUTUBE_CLIENT_ID, "redirect_uri": redirect_uri(platform), "response_type": "code", "scope": " ".join(YT_SCOPES), "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state})


@stylist_required
def connect_start(request, platform: str):
    if platform not in PLATFORMS or not available()[platform]:
        messages.error(request, "この投稿先は、まだつなぐ準備ができていません（運営側のアプリ設定が必要です）。")
        return redirect("reels:settings")
    state = signing.dumps({"stylist": request.stylist.id, "user": request.user.pk, "p": platform}, salt=SALT)
    return redirect(authorize_url(platform, state))


def _connect_instagram(profile, code: str) -> None:
    short, _ = _http("https://api.instagram.com/oauth/access_token", {"client_id": settings.INSTAGRAM_APP_ID, "client_secret": settings.INSTAGRAM_APP_SECRET, "grant_type": "authorization_code", "redirect_uri": redirect_uri("instagram"), "code": code})
    long, _ = _http("https://graph.instagram.com/access_token?" + urllib.parse.urlencode({"grant_type": "ig_exchange_token", "client_secret": settings.INSTAGRAM_APP_SECRET, "access_token": short["access_token"]}))
    token = long["access_token"]
    me, _ = _http(f"{ig_graph()}/me?" + urllib.parse.urlencode({"fields": "user_id,username", "access_token": token}))
    profile.instagram_business_id = str(me.get("user_id") or me.get("id") or "")
    profile.instagram_username = me.get("username", "")
    profile.instagram_access_token = token
    profile.instagram_token_expires_at = timezone.now() + timedelta(seconds=int(long.get("expires_in") or 60 * 24 * 3600))
    profile.post_to_instagram = True
    profile.save()


def _connect_youtube(profile, code: str) -> None:
    tokens, _ = _http("https://oauth2.googleapis.com/token", {"client_id": settings.YOUTUBE_CLIENT_ID, "client_secret": settings.YOUTUBE_CLIENT_SECRET, "redirect_uri": redirect_uri("youtube"), "grant_type": "authorization_code", "code": code})
    if not tokens.get("refresh_token"):
        raise PublishError("長く使えるトークンがもらえませんでした。もう一度つないでください。")
    channels, _ = _http("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    items = channels.get("items") or []
    if not items:
        raise PublishError("このGoogleアカウントには YouTube チャンネルがありません。先にチャンネルを作ってください。")
    profile.youtube_channel_id = items[0]["id"]
    profile.youtube_channel_title = items[0].get("snippet", {}).get("title", "")
    profile.youtube_refresh_token = tokens["refresh_token"]
    profile.post_to_youtube = True
    profile.save()


def _connect_threads(profile, code: str) -> None:
    short, _ = _http(f"{TH_GRAPH}/oauth/access_token", {"client_id": settings.THREADS_APP_ID, "client_secret": settings.THREADS_APP_SECRET, "grant_type": "authorization_code", "redirect_uri": redirect_uri("threads"), "code": code})
    long, _ = _http(f"{TH_GRAPH}/access_token?" + urllib.parse.urlencode({"grant_type": "th_exchange_token", "client_secret": settings.THREADS_APP_SECRET, "access_token": short["access_token"]}))
    token = long["access_token"]
    me, _ = _http(f"{TH_GRAPH}/v1.0/me?" + urllib.parse.urlencode({"fields": "id,username", "access_token": token}))
    profile.threads_user_id = str(me.get("id") or short.get("user_id") or "")
    profile.threads_username = me.get("username", "")
    profile.threads_access_token = token
    profile.threads_token_expires_at = timezone.now() + timedelta(seconds=int(long.get("expires_in") or 60 * 24 * 3600))
    profile.post_to_threads = True
    profile.save()


def connect_callback(request, platform: str):
    from .services import profile_of

    if platform not in PLATFORMS:
        messages.error(request, "投稿先が正しくありません。")
        return redirect("reels:settings")
    if request.GET.get("error"):
        messages.info(request, "つなぐのをやめました。もう一度つなぐときは「つなぐ」を押してください。")
        return redirect("reels:settings")
    try:
        state = signing.loads(request.GET.get("state", ""), salt=SALT, max_age=15 * 60)
    except signing.BadSignature:
        messages.error(request, "時間が経ちすぎたため、つなげませんでした。もう一度お試しください。")
        return redirect("reels:settings")
    user = request.user
    stylist = getattr(user, "stylist", None) if user.is_authenticated else None
    if stylist is None or user.pk != state["user"] or stylist.id != state["stylist"] or state["p"] != platform:
        messages.error(request, "ログインしている人が変わったため、つなげませんでした。もう一度お試しください。")
        return redirect("reels:settings")
    profile = profile_of(stylist)
    try:
        {"instagram": _connect_instagram, "threads": _connect_threads, "youtube": _connect_youtube}[platform](profile, request.GET.get("code", ""))
    except (PublishError, KeyError) as e:
        log.warning("%s とつなげませんでした: %s", platform, e)
        message = str(e) if isinstance(e, PublishError) and not str(e).startswith("HTTP") else "つなげませんでした。もう一度お試しください。"
        messages.error(request, message)
        return redirect("reels:settings")
    messages.success(request, f"{LABELS[platform]} とつなぎました。")
    return redirect("reels:settings")


@stylist_required
@require_POST
def disconnect(request, platform: str):
    from .services import profile_of

    profile = profile_of(request.stylist)
    if platform == "instagram":
        profile.instagram_business_id = profile.instagram_username = profile.instagram_access_token = ""
        profile.instagram_token_expires_at = None
    elif platform == "youtube":
        profile.youtube_channel_id = profile.youtube_channel_title = profile.youtube_refresh_token = ""
    elif platform == "threads":
        profile.threads_user_id = profile.threads_username = profile.threads_access_token = ""
        profile.threads_token_expires_at = None
    else:
        messages.error(request, "投稿先が正しくありません。")
        return redirect("reels:settings")
    profile.save()
    messages.info(request, f"{LABELS[platform]} とのつながりを解除しました。")
    return redirect("reels:settings")


def refresh_instagram_tokens() -> None:
    from .models import ReelProfile

    soon = timezone.now() + timedelta(days=15)
    for profile in ReelProfile.objects.exclude(instagram_access_token="").filter(instagram_token_expires_at__lt=soon):
        try:
            data, _ = _http("https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": profile.instagram_access_token}))
            profile.instagram_access_token = data["access_token"]
            profile.instagram_token_expires_at = timezone.now() + timedelta(seconds=int(data.get("expires_in") or 60 * 24 * 3600))
            profile.save(update_fields=["instagram_access_token", "instagram_token_expires_at", "updated_at"])
        except Exception:  # noqa: BLE001
            log.exception("Instagram のトークンを延ばせませんでした: %s", profile.stylist_id)


def refresh_threads_tokens() -> None:
    from .models import ReelProfile

    soon = timezone.now() + timedelta(days=15)
    for profile in ReelProfile.objects.exclude(threads_access_token="").filter(threads_token_expires_at__lt=soon):
        try:
            data, _ = _http(f"{TH_GRAPH}/refresh_access_token?" + urllib.parse.urlencode({"grant_type": "th_refresh_token", "access_token": profile.threads_access_token}))
            profile.threads_access_token = data["access_token"]
            profile.threads_token_expires_at = timezone.now() + timedelta(seconds=int(data.get("expires_in") or 60 * 24 * 3600))
            profile.save(update_fields=["threads_access_token", "threads_token_expires_at", "updated_at"])
        except Exception:  # noqa: BLE001
            log.exception("Threads のトークンを延ばせませんでした: %s", profile.stylist_id)
