"""django-q2 の定期実行を登録する（qcluster が動いていれば自動で実行される）。

- SNS動画: 予約投稿の実行と数値の取り込み（1分ごと）
- 日次処理: フォロー案内・LINE通数・SNSトークン延長（毎朝8時）
"""

from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "定期実行（予約投稿・日次処理）を django-q2 に登録する"

    def handle(self, *args, **options):
        Schedule.objects.update_or_create(name="reels-housekeeping", defaults={"func": "apps.reels.tasks.housekeeping", "schedule_type": Schedule.MINUTES, "minutes": 1, "repeats": -1})
        Schedule.objects.update_or_create(name="daily-tasks", defaults={"func": "apps.core.tasks.run_daily_tasks", "schedule_type": Schedule.CRON, "cron": "0 8 * * *", "repeats": -1})
        Schedule.objects.update_or_create(name="reels-daily", defaults={"func": "apps.reels.tasks.housekeeping", "kwargs": "daily=True", "schedule_type": Schedule.CRON, "cron": "30 3 * * *", "repeats": -1})
        self.stdout.write(self.style.SUCCESS("定期実行を登録しました（reels-housekeeping / daily-tasks / reels-daily）"))
