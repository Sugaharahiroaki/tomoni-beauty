from . import services
from .models import LineChannel


def suggest_reply(inbound_id: int) -> None:
    services.suggest_reply_for_inbound(inbound_id)


def refresh_quota(channel_id: int) -> None:
    channel = LineChannel.objects.get(pk=channel_id)
    services.refresh_quota_for_channel(channel)
