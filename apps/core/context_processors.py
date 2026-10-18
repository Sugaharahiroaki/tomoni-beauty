from django.conf import settings


def app_context(request):
    stylist = getattr(request, "stylist", None)
    inbox_unread = 0
    if stylist is not None:
        from apps.lineapp.models import InboundMessage

        inbox_unread = InboundMessage.objects.filter(
            stylist=stylist, replied_at__isnull=True, ignored=False
        ).count()
    return {
        "APP_NAME": "TOMONI Beauty",
        "SITE_URL": settings.SITE_URL,
        "STATIC_VERSION": settings.STATIC_VERSION,
        "stylist": stylist,
        "inbox_unread": inbox_unread,
    }
