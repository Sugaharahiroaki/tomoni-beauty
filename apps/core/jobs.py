"""バックグラウンド実行の薄いラッパー（django-q2）。設定 Q_CLUSTER.sync=True なら即時実行。"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def enqueue(func_path: str, *args, **kwargs) -> str | None:
    from django_q.tasks import async_task

    try:
        return async_task(func_path, *args, **kwargs)
    except Exception:  # noqa: BLE001 - キュー投入失敗はログに残して呼び出し元へ伝える
        logger.exception("failed to enqueue %s", func_path)
        raise
