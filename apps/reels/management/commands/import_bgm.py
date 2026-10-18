"""BGMライブラリにまとめて登録する。フォルダ名をカテゴリにするか、--category で指定する。

    python manage.py import_bgm path/to/bgm                 # path/to/bgm/bright/xxx.mp3 → カテゴリ bright
    python manage.py import_bgm static/bgm_seed --flat      # ファイル名の語からカテゴリを推定（開発用サンプル）

登録後、管理画面で「入手元」「ライセンスのメモ」「商用利用の条件を確認した」を入れること。
"""

from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.reels.engine.audio import duration, ffmpeg_available
from apps.reels.models import BgmTrack

GUESS = [(("calm",), "calm"), (("acoustic",), "acoustic"), (("story", "inspir", "emotion"), "emotional"), (("chill", "lofi", "background"), "lofi"), (("upbeat", "festival", "bright"), "bright"), (("country", "daily"), "daily")]


def guess_category(name: str) -> str:
    lower = name.lower()
    for keys, cat in GUESS:
        if any(k in lower for k in keys):
            return cat
    return "daily"


class Command(BaseCommand):
    help = "BGMをまとめて登録する"

    def add_arguments(self, parser):
        parser.add_argument("folder")
        parser.add_argument("--flat", action="store_true", help="サブフォルダを使わず、ファイル名からカテゴリを推定する")
        parser.add_argument("--confirmed", action="store_true", help="商用利用の条件を確認済みとして登録する")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"フォルダが見つかりません: {folder}")
        paths = sorted(folder.glob("*")) if options["flat"] else sorted(folder.glob("*/*"))
        added = 0
        for path in paths:
            if path.suffix.lower() not in (".mp3", ".wav", ".m4a"):
                continue
            category = guess_category(path.stem) if options["flat"] else path.parent.name
            if category not in BgmTrack.CATEGORIES or BgmTrack.objects.filter(title=path.stem).exists():
                continue
            track = BgmTrack(title=path.stem, category=category, duration_sec=round(duration(path), 1) if ffmpeg_available() else 0, license_confirmed=options["confirmed"])
            with path.open("rb") as f:
                track.file.save(path.name, File(f), save=True)
            added += 1
        self.stdout.write(self.style.SUCCESS(f"{added}曲を登録しました"))
