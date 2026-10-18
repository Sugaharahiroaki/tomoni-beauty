from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def badge_class(status: str) -> str:
    return {
        "sent": "ok",
        "done": "ok",
        "posted": "ok",
        "visited": "ok",
        "approved": "accent",
        "draft": "accent",
        "draft_ready": "accent",
        "booked": "accent",
        "pending": "",
        "generating": "warn",
        "transcribing": "warn",
        "structuring": "warn",
        "uploaded": "warn",
        "failed": "danger",
        "cancelled": "danger",
        "no_show": "danger",
        "discarded": "",
        "skipped": "",
    }.get(status or "", "")


@register.filter
def jadate(value) -> str:
    """2026/10/18(土) 形式。"""
    if not value:
        return ""
    if hasattr(value, "tzinfo") and value.tzinfo is not None:
        value = timezone.localtime(value)
    weekdays = "月火水木金土日"
    return f"{value.month}/{value.day}({weekdays[value.weekday()]})"


@register.filter
def jadatetime(value) -> str:
    if not value:
        return ""
    value = timezone.localtime(value)
    return f"{jadate(value)} {value:%H:%M}"


@register.filter
def days_until(value) -> str:
    if not value:
        return ""
    today = timezone.localdate()
    diff = (value - today).days
    if diff == 0:
        return "今日"
    if diff == 1:
        return "明日"
    if diff < 0:
        return f"{-diff}日前"
    return f"{diff}日後"


@register.filter
def initial(value: str) -> str:
    return (value or "?").strip()[:1]


@register.filter
def route_label(route: str) -> str:
    return {"copy": "コピー送信", "reply": "Reply返信", "push": "Push送信"}.get(route, route or "")


@register.simple_tag(takes_context=True)
def active(context, *names) -> str:
    request = context.get("request")
    if not request or not getattr(request, "resolver_match", None):
        return ""
    current = f"{request.resolver_match.namespace}:{request.resolver_match.url_name}"
    for n in names:
        if current == n or (n.endswith(":*") and current.startswith(n[:-1])):
            return "active"
    return ""
