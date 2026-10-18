from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def stylist_required(view_func):
    """ログイン済み かつ 美容師レコードが存在することを要求する。"""

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if getattr(request, "stylist", None) is None:
            return redirect("accounts:onboarding_basic")
        return view_func(request, *args, **kwargs)

    return _wrapped


def get_object_for_stylist(model, stylist, **lookup):
    """テナント境界を越えた取得を防ぐ共通ヘルパー。"""
    from django.shortcuts import get_object_or_404

    return get_object_or_404(model, stylist=stylist, **lookup)
