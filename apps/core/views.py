import hmac
import json

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .decorators import stylist_required
from .services import build_digest, build_today, monthly_stats


@stylist_required
def today(request):
    stylist = request.stylist
    if not stylist.onboarding_completed:
        return redirect("accounts:onboarding_basic")
    context = build_today(stylist)
    return render(request, "core/today.html", context)


@stylist_required
def stats(request):
    context = monthly_stats(request.stylist, months=6)
    return render(request, "core/stats.html", context)


@stylist_required
def settings_menu(request):
    channel = getattr(request.stylist, "line_channel", None)
    return render(request, "core/settings_menu.html", {"channel": channel})


def manifest(request):
    data = {
        "name": "TOMONI Beauty",
        "short_name": "TOMONI",
        "description": "施術後30秒の音声メモから、カルテ・LINE文面・SNS投稿を自動作成",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#faf7f2",
        "theme_color": "#b85c4a",
        "lang": "ja",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json")


def service_worker(request):
    body = render_to_string("core/sw.js", {"version": settings.STATIC_VERSION})
    response = HttpResponse(body, content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response


def offline(request):
    return render(request, "core/offline.html")


def terms(request):
    return render(request, "core/terms.html")


def privacy(request):
    return render(request, "core/privacy.html")


def health(request):
    return JsonResponse({"status": "ok"})


def _internal_token_ok(request) -> bool:
    expected = settings.INTERNAL_API_TOKEN
    if not expected:
        return False
    provided = request.headers.get("X-Internal-Token") or request.GET.get("token", "")
    return hmac.compare_digest(str(provided), str(expected))


@csrf_exempt
@require_POST
def internal_daily(request):
    """n8n などから1日1回呼ぶ: フォロー案内の下書き生成・通数取得など。"""
    if not _internal_token_ok(request):
        return HttpResponseForbidden("forbidden")
    from .tasks import run_daily_tasks

    summary = run_daily_tasks()
    return JsonResponse(summary)


@csrf_exempt
@require_GET
def internal_digest(request):
    """各美容師の「今日のおすすめ対応」をJSONで返す（n8n からメール/通知に使う）。"""
    if not _internal_token_ok(request):
        return HttpResponseForbidden("forbidden")
    return JsonResponse({"stylists": build_digest()}, json_dumps_params={"ensure_ascii": False})


def json_error(message: str, status: int = 400):
    return JsonResponse({"error": message}, status=status)


def parse_json_body(request) -> dict:
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}
