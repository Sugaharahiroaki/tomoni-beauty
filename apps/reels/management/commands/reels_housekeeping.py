"""予約投稿の実行・数値の取り込み・トークン延長。

    python manage.py reels_housekeeping            # 1回だけ
    python manage.py reels_housekeeping --loop     # 60秒ごとにずっと（systemd で常駐させる場合）
    python manage.py reels_housekeeping --daily    # トークン延長も行う

django-q2 のスケジュールに登録する場合は `python manage.py setup_schedules`。
"""

import time

from django.core.management.base import BaseCommand

from apps.reels.services import housekeeping


class Command(BaseCommand):
    help = "SNS動画の予約投稿・数値取り込み・トークン延長"

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--daily", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **options):
        while True:
            summary = housekeeping(daily=options["daily"])
            self.stdout.write(str(summary))
            if not options["loop"]:
                break
            time.sleep(options["interval"])
