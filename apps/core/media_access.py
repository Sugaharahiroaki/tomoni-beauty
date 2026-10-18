"""写真・動画・録音のファイル（/media/）を、見てよい人にだけ渡す。

- できあがった動画とサムネイル（stylist_<id>/reels/renders/）は、だれでも見られる
  （Instagram・Threads が動画を取りに来るため。ファイル名は推測できない長い名前）
- それ以外の美容師のファイル（施術写真・音声・レシート・明細・素材）は、その美容師にログインしている人だけ
- BGM・撮影の見本は、ログインしている人なら見られる
- 本番（DEBUG=False）では、確かめたあとのファイルの送り出しを Nginx にまかせる（X-Accel-Redirect）
"""

import mimetypes
import posixpath
import re
import urllib.parse
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse

STYLIST_FILE = re.compile(r"^stylist_(?P<stylist>\d+)/(?P<rest>.+)$")
PUBLIC_RENDER = re.compile(r"^reels/renders/[^/]+\.(mp4|jpg)$")
LOGGED_IN_ONLY = ("bgm/", "examples/")


def allowed(user, path: str) -> bool:
    m = STYLIST_FILE.match(path)
    if m:
        if PUBLIC_RENDER.match(m.group("rest")):
            return True
        if not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        stylist = getattr(user, "stylist", None)
        return bool(stylist and str(stylist.id) == m.group("stylist"))
    if path.startswith(LOGGED_IN_ONLY):
        return bool(user.is_authenticated)
    return bool(user.is_authenticated and user.is_staff)


def serve_media(request, path: str):
    clean = posixpath.normpath(path).lstrip("/")
    if clean.startswith("..") or clean != path.lstrip("/") or not allowed(request.user, clean):
        raise Http404
    full = Path(settings.MEDIA_ROOT) / clean
    if not full.is_file():
        raise Http404
    content_type = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
    if settings.DEBUG or not settings.MEDIA_ACCEL_REDIRECT:
        response = FileResponse(full.open("rb"), content_type=content_type)
        response["Cache-Control"] = "private, max-age=3600"
        return response
    response = HttpResponse(content_type=content_type)
    response["X-Accel-Redirect"] = "/protected-media/" + urllib.parse.quote(clean)
    return response
