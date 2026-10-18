"""Instagram リール・YouTube ショート・Threads への投稿と、数値の取り込み。

接続情報（トークン）が無いときは、投稿したことにしてローカルに記録する（お試し投稿）。
Instagram・Threads の投稿には、動画がインターネットから見られるURL（PUBLIC_MEDIA_BASE_URL）が必要。
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import PostMetric, ReelPost

log = logging.getLogger(__name__)
TH_GRAPH = "https://graph.threads.net"
TH_TEXT_LIMIT = 500
AI_NOTICE = "※ナレーションはAI音声です。"


def ig_graph() -> str:
    return f"https://graph.instagram.com/{settings.INSTAGRAM_GRAPH_VERSION}"


class PublishError(RuntimeError):
    pass


def _http(url, data=None, method=None, headers=None, timeout=60):
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}, dict(r.headers)
    except urllib.error.HTTPError as e:
        raise PublishError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise PublishError(f"接続エラー: {e}") from e


def uses_ai_voice(post: ReelPost) -> bool:
    return bool(post.ai_label and post.narration_mode == "ai")


def caption_for(post: ReelPost, platform: str) -> str:
    tags = " ".join(f"#{h}" for h in post.hashtags)
    notice = f"\n\n{AI_NOTICE}" if uses_ai_voice(post) else ""
    if platform == "instagram":
        return f"{post.ig_caption}{notice}\n\n{tags}".strip()
    if platform == "threads":
        tag = f"\n\n#{post.hashtags[0]}" if post.hashtags else ""
        room = TH_TEXT_LIMIT - len(notice) - len(tag)
        body = post.ig_caption if len(post.ig_caption) <= room else post.ig_caption[: max(room - 1, 0)] + "…"
        return f"{body}{notice}{tag}".strip()
    return f"{post.yt_description}{notice}\n\n{tags}".strip()


def public_url(field) -> str:
    base = (settings.PUBLIC_MEDIA_BASE_URL or "").rstrip("/")
    if not base:
        raise PublishError("動画の公開URL（PUBLIC_MEDIA_BASE_URL）が設定されていません。")
    return f"{base}/{field.name}"


def publish_instagram(post: ReelPost, profile) -> dict:
    if not profile.instagram_connected:
        return {"mock": True, "id": f"mock-ig-{post.id.hex[:8]}"}
    if profile.instagram_token_expires_at and profile.instagram_token_expires_at < timezone.now():
        raise PublishError("Instagram とのつながりが切れています。「SNS動画の設定」でつなぎ直してください。")
    token = profile.instagram_access_token
    created, _ = _http(f"{ig_graph()}/{profile.instagram_business_id}/media", {"media_type": "REELS", "video_url": public_url(post.video), "caption": caption_for(post, "instagram"), "share_to_feed": "true", "access_token": token})
    container = created["id"]
    for _ in range(60):
        status, _ = _http(f"{ig_graph()}/{container}?fields=status_code&access_token={token}")
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            raise PublishError("Instagram が動画を受け付けませんでした。")
        time.sleep(10)
    published, _ = _http(f"{ig_graph()}/{profile.instagram_business_id}/media_publish", {"creation_id": container, "access_token": token})
    return {"id": published["id"]}


def publish_threads(post: ReelPost, profile) -> dict:
    if not profile.threads_connected:
        return {"mock": True, "id": f"mock-th-{post.id.hex[:8]}"}
    if profile.threads_token_expires_at and profile.threads_token_expires_at < timezone.now():
        raise PublishError("Threads とのつながりが切れています。「SNS動画の設定」でつなぎ直してください。")
    token = profile.threads_access_token
    base = f"{TH_GRAPH}/v1.0"
    created, _ = _http(f"{base}/{profile.threads_user_id}/threads", {"media_type": "VIDEO", "video_url": public_url(post.video), "text": caption_for(post, "threads"), "access_token": token})
    container = created["id"]
    for _ in range(60):
        time.sleep(10)
        status, _ = _http(f"{base}/{container}?fields=status,error_message&access_token={token}")
        if status.get("status") == "FINISHED":
            break
        if status.get("status") in ("ERROR", "EXPIRED"):
            raise PublishError(f"Threads が動画を受け付けませんでした。{status.get('error_message', '')}".strip())
    published, _ = _http(f"{base}/{profile.threads_user_id}/threads_publish", {"creation_id": container, "access_token": token})
    return {"id": published["id"]}


def google_access_token(refresh_token: str) -> str:
    data, _ = _http("https://oauth2.googleapis.com/token", {"client_id": settings.YOUTUBE_CLIENT_ID, "client_secret": settings.YOUTUBE_CLIENT_SECRET, "refresh_token": refresh_token, "grant_type": "refresh_token"})
    return data["access_token"]


def publish_youtube(post: ReelPost, profile) -> dict:
    if not profile.youtube_connected:
        return {"mock": True, "id": f"mock-yt-{post.id.hex[:8]}"}
    token = google_access_token(profile.youtube_refresh_token)
    meta = {
        "snippet": {"title": f"{post.yt_title} #shorts"[:100], "description": caption_for(post, "youtube"), "categoryId": "26", "defaultLanguage": "ja"},
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": uses_ai_voice(post)},
    }
    _, headers = _http("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status", json.dumps(meta).encode(), headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-Upload-Content-Type": "video/mp4"})
    upload_url = headers.get("Location") or headers.get("location")
    with open(post.video.path, "rb") as f:
        video, _ = _http(upload_url, f.read(), method="PUT", headers={"Content-Type": "video/mp4"}, timeout=600)
    return {"id": video["id"]}


def publish_post(post: ReelPost) -> None:
    """予約時間になった投稿を、設定された投稿先に出す（片方が失敗しても、もう片方は出す）"""
    from .services import profile_of

    profile = profile_of(post.stylist)
    results = dict(post.publish_result or {})
    errors = []
    targets = [("instagram", profile.post_to_instagram, publish_instagram), ("youtube", profile.post_to_youtube, publish_youtube), ("threads", profile.post_to_threads, publish_threads)]
    if not any(enabled for _, enabled, _ in targets):
        post.status, post.error = "FAILED", "投稿先が選ばれていません。「SNS動画の設定」で投稿先を選んでください。"
        post.save(update_fields=["status", "error", "updated_at"])
        return
    for platform, enabled, func in targets:
        if not enabled or results.get(platform, {}).get("id"):
            continue
        try:
            results[platform] = func(post, profile)
        except Exception as e:  # noqa: BLE001
            log.exception("%s への投稿に失敗", platform)
            errors.append(f"{platform}: {e}")
    post.publish_result = results
    if errors and not any(r.get("id") for r in results.values()):
        post.status, post.error = "FAILED", "\n".join(errors)
    else:
        post.status, post.published_at, post.error = "PUBLISHED", timezone.now(), "\n".join(errors)
    post.save()


def best_time(now=None):
    """よく見られる時間の次の枠（既定は 12時・19時）"""
    now = timezone.localtime(now or timezone.now())
    hours = sorted(int(h) for h in str(settings.SOCIAL_BEST_HOURS).split(",") if h.strip())
    for day in range(0, 3):
        base = (now + timedelta(days=day)).replace(minute=0, second=0, microsecond=0)
        for h in hours:
            slot = base.replace(hour=h)
            if slot > now + timedelta(minutes=15):
                return slot
    return now + timedelta(hours=1)


def fetch_metrics(post: ReelPost) -> None:
    from .services import profile_of

    profile = profile_of(post.stylist)
    ig = (post.publish_result or {}).get("instagram", {})
    if ig.get("id") and not ig.get("mock") and profile.instagram_access_token:
        data, _ = _http(f"{ig_graph()}/{ig['id']}/insights?metric=views,reach,likes,comments,shares,saved&access_token={profile.instagram_access_token}")
        values = {m["name"]: m["values"][0]["value"] for m in data.get("data", [])}
        PostMetric.objects.create(post=post, platform="instagram", views=values.get("views"), reach=values.get("reach"), likes=values.get("likes"), comments=values.get("comments"), shares=values.get("shares"), saves=values.get("saved"))
    yt = (post.publish_result or {}).get("youtube", {})
    if yt.get("id") and not yt.get("mock") and profile.youtube_refresh_token:
        token = google_access_token(profile.youtube_refresh_token)
        data, _ = _http(f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={yt['id']}", headers={"Authorization": f"Bearer {token}"})
        stats = (data.get("items") or [{}])[0].get("statistics", {})
        PostMetric.objects.create(post=post, platform="youtube", views=int(stats.get("viewCount", 0)), likes=int(stats.get("likeCount", 0)), comments=int(stats.get("commentCount", 0)))
    th = (post.publish_result or {}).get("threads", {})
    if th.get("id") and not th.get("mock") and profile.threads_access_token:
        data, _ = _http(f"{TH_GRAPH}/v1.0/{th['id']}/insights?metric=views,likes,replies,reposts,quotes,shares&access_token={profile.threads_access_token}")
        values = {m["name"]: (m.get("values") or [{}])[0].get("value") for m in data.get("data", [])}
        PostMetric.objects.create(post=post, platform="threads", views=values.get("views"), likes=values.get("likes"), comments=values.get("replies"), shares=sum(values.get(k) or 0 for k in ("reposts", "quotes", "shares")))
