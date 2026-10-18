"""顧客まわりのドメイン操作（LINE友だちの紐付け・統合）。"""
from __future__ import annotations

from django.db import transaction

from .models import Customer


@transaction.atomic
def merge_line_shell_into(shell: Customer, target: Customer) -> Customer:
    """LINEから自動作成された仮顧客(shell)を既存顧客(target)に統合する。

    LINE情報と受信/送信メッセージを target に移し、shell を削除する。
    """
    if shell.stylist_id != target.stylist_id:
        raise ValueError("別の美容師の顧客は統合できません")
    if target.line_user_id and target.line_user_id != shell.line_user_id:
        raise ValueError("統合先にはすでに別のLINEアカウントが紐付いています")

    from apps.lineapp.models import InboundMessage, Message

    line_user_id = shell.line_user_id
    # 一意制約を避けるため、先に shell 側を外す
    shell.line_user_id = None
    shell.save(update_fields=["line_user_id"])

    target.line_user_id = line_user_id
    target.line_display_name = shell.line_display_name or target.line_display_name
    target.line_picture_url = shell.line_picture_url or target.line_picture_url
    target.line_followed = shell.line_followed
    target.line_blocked_at = shell.line_blocked_at
    target.needs_review = False
    target.save()

    InboundMessage.objects.filter(customer=shell).update(customer=target)
    Message.objects.filter(customer=shell).update(customer=target)
    shell.delete()
    return target
