import json

from django.core.management.base import BaseCommand

from apps.core.tasks import run_daily_tasks


class Command(BaseCommand):
    help = "日次処理（フォロー案内の下書き生成・LINE通数の取得）を実行する"

    def handle(self, *args, **options):
        summary = run_daily_tasks()
        self.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2))
