"""django-q2 から呼ばれるタスク関数（文字列パスで参照されるので名前を変えない）。"""
import logging

from apps.accounts.models import Stylist

from . import services

logger = logging.getLogger(__name__)


def transcribe_answer(answer_id: int) -> None:
    services.transcribe_answer(answer_id)


def build_episodes(stylist_id: int) -> int:
    stylist = Stylist.objects.get(pk=stylist_id)
    return services.build_episodes_from_interview(stylist)
