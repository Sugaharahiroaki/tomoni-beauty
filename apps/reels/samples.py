"""見本の動画（デモ用）。

SOYON なんば店向けに作った4本を、アプリの型（recipes.py）で再現する。
- 作品集（color_catalog）: 美容師から預かった実写真（demo_assets/photos）
- 自己紹介・スタイリストの思い・スタイリストの1日: 本人映像の代わりに AI で作った架空のスタイリストの5秒クリップ（demo_assets/stylist_clips）

素材ファイルが無い見本は作らない（リポジトリには素材を入れていないため）。
テロップ・ナレーションの {サロン} {名前} {エリア} はデモ美容師の情報で埋める。
"""
from __future__ import annotations

from pathlib import Path

from django.core.files import File

from . import services
from .ai import fill_slot_text, forbidden_terms, pii_summary
from .models import BgmTrack, ReelPost

HASH_AREA = ["なんば美容室", "難波ヘアサロン", "大阪美容室"]

# 素材: 名前 → (種類, 撮影リストの項目, 顔が写っているか)
SAMPLES = [
    {
        "key": "catalog",
        "post_type": "suggestion",
        "template": "color_catalog",
        "theme": "ブリーチで出せる色、6パターン",
        "menu_items": ["ブリーチ", "カラー"],
        "bgm": "lofi",
        "assets": {
            "platinum_bob_back": ("photo", "hero", False),
            "navy_bob_back": ("photo", "work3", False),
            "pink_bob_side": ("photo", "work1", False),
            "copper_long_back": ("photo", "work2", False),
            "black_blue_ends_back": ("photo", "work4", False),
            "blonde_bob_back": ("photo", "work5", False),
            "beige_blonde_long_back": ("photo", "work6", False),
            "highlight_long_back": ("photo", "closing", False),
            "ash_blonde_ends_hand": ("photo", "", False),
            # 顔が写っている写真。顔出し不可の投稿なので「使用不可」になることの見本
            "highlight_side_hand": ("photo", "", True),
            "purple_inner_side": ("photo", "", True),
        },
        "scenes": [
            ("フック", "ブリーチで、ここまで変わる", "ブリーチで出せる色、ぜんぶ見せます。", 2.6, [("platinum_bob_back", {"sec": 1.3}), ("navy_bob_back", {"sec": 1.3, "motion": "static"})]),
            ("①", "① くすみピンク", "ひとつめ、くすみピンク。", 2.2, [("pink_bob_side", {"motion": "zoom_out", "tight": 1.1, "focus_x": 0.45, "focus_y": 0.4})]),
            ("②", "② コッパーオレンジ", "ふたつめ、コッパーオレンジ。", 2.2, [("copper_long_back", {"tight": 1.15, "focus_y": 0.4})]),
            ("③", "③ ネイビー", "みっつめ、ネイビー。", 2.2, [("navy_bob_back", {"tight": 1.15})]),
            ("④", "④ 裾だけブルー", "よっつめ、裾だけブルー。", 2.2, [("black_blue_ends_back", {"motion": "zoom_out", "tight": 1.1, "focus_y": 0.55})]),
            ("⑤", "⑤ ホワイトブロンド", "いつつめ、ホワイトブロンド。", 2.2, [("blonde_bob_back", {"tight": 1.15})]),
            ("⑥", "⑥ ミルクティーベージュ", "むっつめ、ミルクティーベージュ。", 2.2, [("beige_blonde_long_back", {"motion": "pan_right", "tight": 1.2})]),
            ("締め", "伸びても自然がいい人は\nハイライト", "伸びても自然がいい人は、ハイライトがおすすめです。", 2.8, [("highlight_long_back", {"tight": 1.2, "focus_y": 0.4})]),
        ],
        "cta": ("{サロン}", "なりたい色、DMで相談OK", "ash_blonde_ends_hand"),
        "ig_caption": "ブリーチで出せる色、6パターン。\n\nくすみピンク／コッパーオレンジ／ネイビー／裾ブルー／ホワイトブロンド／ミルクティーベージュ。\nどれも「色落ちしてからも、きれい」を基準に配合しています。\n\n伸びてきたときの境目が気になる方は、ハイライトで根元をぼかすのがおすすめです。\nなりたい色が決まっていなくても大丈夫。写真を見せてもらえれば、髪の状態に合わせてご提案します。\n\nご予約・ご相談はプロフィールのリンク、またはDMから。",
        "hashtags": ["ブリーチカラー", "ハイトーンカラー", "韓国ヘア", "くすみピンク", "ネイビーカラー", "裾カラー", "ミルクティーベージュ", "ハイライトカラー", *HASH_AREA, "フリーランス美容師"],
        "yt_title": "ブリーチで出せる色、6パターン【{エリア}の美容室】",
        "yt_description": "くすみピンク、コッパーオレンジ、ネイビー、裾ブルー、ホワイトブロンド、ミルクティーベージュ。色落ちしてからもきれいな配合で。",
    },
    {
        "key": "intro",
        "post_type": "personality",
        "template": "self_intro",
        "theme": "はじめまして、{サロン}の{名前}です",
        "menu_items": ["ハイライト", "ベージュ系カラー"],
        "bgm": "bright",
        "assets": {
            "clip:intro": ("video", "greeting", True),
            "highlight_long_back": ("photo", "works", False),
            "beige_blonde_long_back": ("photo", "works", False),
            "pink_bob_side": ("photo", "works", False),
            "blonde_bob_back": ("photo", "works", False),
            "clip:counsel": ("video", "counsel", True),
            "clip:cut": ("video", "work", True),
            "clip:finish": ("video", "finish", True),
        },
        "scenes": [
            ("フック", "はじめまして\n{サロン}の{名前}です", "はじめまして。{サロン}でスタイリストをしている、{名前}です。", 2.8, [("clip:intro", {"video_start": 0.2})]),
            ("得意", "得意なのは\nハイライトとベージュ系", "得意なのは、ハイライトと、ベージュ系のカラーです。", 2.4, [("highlight_long_back", {"sec": 1.2, "focus_y": 0.4}), ("beige_blonde_long_back", {"motion": "zoom_out"})]),
            ("得意2", "ブリーチカラーも\nおまかせください", "ブリーチカラーも、おまかせください。", 2.2, [("pink_bob_side", {"sec": 1.1, "motion": "zoom_out"}), "blonde_bob_back"]),
            ("こだわり", "最初に聞くのは\n「なりたくない髪」", "最初にいつも聞くのは、なりたくない髪のことです。", 2.6, ["clip:counsel"]),
            ("理由", "そこに一番\n本音が出るから", "そこに、いちばん本音が出るので。", 2.4, ["clip:cut"]),
            ("締め", "鏡を見た瞬間\n笑ってもらえたら", "鏡を見た瞬間、笑ってもらえたら、うれしいです。", 2.6, ["clip:finish"]),
        ],
        "cta": ("{サロン} {名前}", "ご予約はプロフィールのリンクから", "clip:intro"),
        "ig_caption": "はじめまして。{サロン}でスタイリストをしている{名前}です。\n\n得意なのはハイライトとベージュ系のカラー。ブリーチカラーもおまかせください。\n\n初めての方にはいつも「今までで一番困った髪型」を聞いています。やりたいことより、やりたくないことの方が本音が出るからです。\n\n{場所}。ご予約・ご相談はプロフィールのリンク、またはDMからどうぞ。",
        "hashtags": ["はじめまして", "ハイライトカラー", "ベージュカラー", "ブリーチカラー", *HASH_AREA, "美容師", "スタイリスト紹介"],
        "yt_title": "はじめまして、{サロン}の{名前}です",
        "yt_description": "{サロン}でスタイリストをしている{名前}です。得意なのはハイライトとベージュ系カラー。",
    },
    {
        "key": "story",
        "post_type": "personality",
        "template": "stylist_story",
        "theme": "美容師になったきっかけ",
        "menu_items": [],
        "bgm": "emotional",
        "assets": {
            "clip:morning": ("video", "back", True),
            "clip:prep": ("video", "tools", True),
            "clip:finish": ("video", "hands", True),
            "clip:mixing": ("video", "salon", True),
            "clip:blowdry": ("video", "salon", True),
            "highlight_medium_back": ("photo", "hero", False),
            "copper_long_back": ("photo", "hero", False),
            "clip:intro": ("video", "smile", True),
        },
        "scenes": [
            ("フック", "最初は、美容師に\nなるつもりなかったんです", "最初は、美容師になるつもり、なかったんです。", 2.8, ["clip:morning"]),
            ("過去", "きっかけは中学生のとき\n母の前髪を切ったこと", "きっかけは中学生のとき。母の前髪を切ったことでした。", 2.8, ["clip:prep"]),
            ("転機", "鏡を見て笑ってくれた顔が\n忘れられなくて", "鏡を見て笑ってくれた顔が、忘れられなくて。", 2.8, ["clip:finish"]),
            ("修業", "アシスタント時代\n色落ちで悩む人をたくさん見た", "アシスタント時代は、色落ちで悩むお客様を、たくさん見ました。", 2.8, ["clip:mixing"]),
            ("今", "だから今は\n3週間後の髪まで考えて染める", "だから今は、三週間後の髪まで考えて、染めています。", 2.8, ["clip:blowdry"]),
            ("作品", "伸びても、色が落ちても\nきれいなように", "伸びても、色が落ちても、きれいなように。", 2.4, [("highlight_medium_back", {"sec": 1.2}), ("copper_long_back", {"motion": "zoom_out", "focus_y": 0.4})]),
            ("締め", "あの日の母みたいに\n笑ってもらえるように", "あの日の母みたいに、笑ってもらえるように。", 2.8, [("clip:intro", {"video_start": 0.2})]),
        ],
        "cta": ("{サロン} {名前}", "フォローして、また見に来てください", "clip:finish"),
        "ig_caption": "最初は、美容師になるつもりはありませんでした。\n\nきっかけは中学生のとき、母の前髪を切ったこと。鏡を見て笑ってくれた顔が、今でも忘れられません。\n\nアシスタント時代は、色落ちにがっかりして戻ってくるお客様をたくさん見てきました。だから今は「染めた日」より「3週間後」の髪を考えて配合しています。\n\n{サロン}で、お待ちしています。",
        "hashtags": ["美容師になった理由", "美容師の思い", "カラーが得意", *HASH_AREA, "美容師", "スタイリスト紹介"],
        "yt_title": "美容師になったきっかけ｜{サロン} {名前}",
        "yt_description": "母の前髪を切った日から、3週間後の髪を考えて染めるようになるまで。",
        "episodes": ["母の髪を切った日", "3週間後を考えるようになった修業時代"],
    },
    {
        "key": "day",
        "post_type": "personality",
        "template": "daily",
        "theme": "{エリア}の美容師の1日",
        "menu_items": [],
        "bgm": "lofi",
        "assets": {
            "clip:morning": ("video", "open", True),
            "clip:prep": ("video", "prep", True),
            "clip:counsel": ("video", "counsel", True),
            "clip:mixing": ("video", "work", True),
            "clip:cut": ("video", "work", True),
            "clip:blowdry": ("video", "blow", True),
            "platinum_bob_back": ("photo", "works", False),
            "navy_bob_back": ("photo", "works", False),
            "beige_blonde_long_back": ("photo", "works", False),
            "clip:finish": ("video", "close", True),
        },
        "scenes": [
            ("フック", "{エリア}の美容師の1日", "{エリア}で働く美容師の、一日です。", 2.4, ["clip:morning"]),
            ("準備", "8:45 開店前の準備", "開店前は、道具のセットから。", 2.2, ["clip:prep"]),
            ("カウンセリング", "10:00 まずはカウンセリング", "一人目のお客様。まずはカウンセリング。", 2.2, ["clip:counsel"]),
            ("施術", "11:30 ブリーチ毛のカラー", "ブリーチ毛は、配合をいつもより慎重に。", 2.2, ["clip:mixing"]),
            ("施術2", "14:00 カット", "午後は、カット。", 2.0, ["clip:cut"]),
            ("仕上げ", "17:00 仕上げのブロー", "夕方は、仕上げのブロー。", 2.2, ["clip:blowdry"]),
            ("今日の仕上がり", "今日の仕上がり", "今日の仕上がりは、こんな感じ。", 2.4, [("platinum_bob_back", {"sec": 0.8}), ("navy_bob_back", {"sec": 0.8, "motion": "zoom_out"}), "beige_blonde_long_back"]),
            ("締め", "今日も\nおつかれさまでした", "今日も、おつかれさまでした。", 2.4, ["clip:finish"]),
        ],
        "cta": ("{サロン} {名前}", "空き状況はプロフィールのリンクから", "clip:prep"),
        "ig_caption": "{エリア}で働く美容師の1日。\n\n8:45 開店前の準備\n10:00 1人目はカウンセリングから\n11:30 ブリーチ毛のカラー\n14:00 カット\n17:00 仕上げのブロー\n\n夜21時以降の受付もしています。空き状況はプロフィールのリンクからどうぞ。",
        "hashtags": ["美容師の1日", "美容師vlog", "サロンワーク", *HASH_AREA, "美容師"],
        "yt_title": "{エリア}の美容師の1日【vlog】",
        "yt_description": "開店前の準備から仕上げのブローまで。{サロン}のスタイリストの1日。",
    },
]


def _asset_path(name: str, photo_dir: Path, clip_dir: Path) -> Path:
    if name.startswith("clip:"):
        return Path(clip_dir) / f"{name.split(':', 1)[1]}.mp4"
    return Path(photo_dir) / f"{name}.jpg"


def available(sample: dict, photo_dir: Path, clip_dir: Path) -> bool:
    return all(_asset_path(name, photo_dir, clip_dir).exists() for name in sample["assets"])


def create_sample_post(stylist, sample: dict, photo_dir: Path, clip_dir: Path, render: bool = False) -> ReelPost:
    from apps.profiles.models import Episode

    post = services.start_post(stylist, post_type=sample["post_type"], template_key=sample["template"], menu_items=list(sample["menu_items"]), import_photos=False)
    fill = lambda text: fill_slot_text(text, post).replace("{場所}", stylist.salon_access or stylist.salon_name)  # noqa: E731
    post.theme_title = fill(sample["theme"])
    ids = {}
    for name, (kind, slot, face) in sample["assets"].items():
        path = _asset_path(name, photo_dir, clip_dir)
        with path.open("rb") as f:
            asset = services.save_asset(post, File(f, name=path.name), path.name, "video/mp4" if kind == "video" else "image/jpeg", path.stat().st_size, kind, slot, face_visible=face)
        ids[name] = str(asset.id)

    def shot(spec):
        name, extra = (spec, {}) if isinstance(spec, str) else spec
        base = {"asset_id": ids[name], "motion": "static" if name.startswith("clip:") else "zoom_in", "tight": 1.0, "focus_x": 0.5, "focus_y": 0.45, "sec": None, "video_start": None}
        base.update(extra)
        return base

    episode_ids = [str(e.id) for e in Episode.objects.filter(stylist=stylist, title__in=sample.get("episodes", []))]
    title, text, bg = sample["cta"]
    script = {
        "theme_title": post.theme_title,
        "hook_type": "見本",
        "scenes": [{"role": r, "caption": fill(c), "narration": fill(n), "duration": d, "shots": [shot(s) for s in shots]} for r, c, n, d, shots in sample["scenes"]],
        "cta": {"title": fill(title), "text": fill(text), "narration": "", "background_asset_id": ids[bg], "duration": 2.8},
        "episode_ids": episode_ids,
        "bgm_category": sample["bgm"],
        "ig_caption": fill(sample["ig_caption"]),
        "hashtags": list(sample["hashtags"]),
        "yt_title": fill(sample["yt_title"]),
        "yt_description": fill(sample["yt_description"]),
        "notes_for_stylist": "",
    }
    first = sample["scenes"][0]
    post.selected_hook = {"type": "result", "label": "結果先出し", "text": fill(first[1]).replace("\n", ""), "visual": "", "hype": []}
    post.hooks = [post.selected_hook]
    post.output_format = "reel"
    post.cover_text = post.selected_hook["text"][:60]
    post.script = script
    post.episode_ids = episode_ids
    post.ig_caption, post.hashtags, post.yt_title, post.yt_description = script["ig_caption"], script["hashtags"], script["yt_title"], script["yt_description"]
    post.narration_mode = "ai"
    post.bgm = BgmTrack.objects.filter(category=sample["bgm"]).first() or BgmTrack.objects.first()
    post.status = "REVIEW"
    source = "美容師から預かった実写真" if sample["template"] == "color_catalog" else "本人映像は AI で作った架空のスタイリスト、作品写真は美容師から預かった実写真"
    post.notes = [f"見本：{source}。投稿前に本人の素材へ差し替えてください"]
    post.pii_check = pii_summary(script, forbidden_terms(post))
    from .content import finalize_checks

    finalize_checks(post)
    post.save()
    if render:
        from .render_service import render_post

        render_post(post)
        post.refresh_from_db()
    return post


def create_sample_posts(stylist, photo_dir: Path, clip_dir: Path, render: bool = False) -> list[ReelPost]:
    return [create_sample_post(stylist, s, photo_dir, clip_dir, render) for s in SAMPLES if available(s, photo_dir, clip_dir)]
