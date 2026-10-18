"""投稿の5つの型（美容師向け）と、型ごとの撮影リスト。

frame は構図の型（カメラのガイド線に使う）：
closeup＝毛先・質感のアップ / hands＝手元 / back＝後ろ姿 / mirror＝鏡越し / tools＝道具・薬剤 / wide＝店内 / overhead＝真上

{お客様} はそのまま。お客様の顔は「顔出しOK」のときだけ写してよい（既定は後ろ姿・手元）。
"""

TEMPLATES = {
    "before_after": {
        "label": "ビフォーアフター",
        "goal": "指名・問い合わせにつなげる",
        "seconds": (15, 20),
        "bgm_categories": ["bright", "lofi", "daily"],
        "cta": "予約",
        "slots": [
            {"key": "after_hero", "frame": "closeup", "role": "フック", "what": "仕上がりの一番きれいなところ（毛先・ツヤ）", "how": "明るい所で、髪に20〜30cmまで寄って。顔は入れない", "recommend": "video", "work": 6, "caption": "色落ちが早い人へ", "narration": "色落ちが早くて困ってる人、見てください。"},
            {"key": "before", "frame": "back", "role": "悩み", "what": "施術前の後ろ姿・毛先", "how": "後ろから。首より上は入れなくてOK", "recommend": "photo", "work": 1, "caption": "施術前", "narration": "最初はこんな感じでした。"},
            {"key": "bowl", "frame": "tools", "role": "工夫", "what": "薬剤・カラーボウル・道具", "how": "真上か斜め上から", "recommend": "photo", "work": 2, "caption": "赤みを抑える配合", "narration": "赤みが出にくいように、ひとさじ混ぜます。"},
            {"key": "hands", "frame": "hands", "role": "施術", "what": "塗布・カットしている手元", "how": "少し横から。手と髪が真ん中に", "recommend": "video", "work": 3, "caption": "根元からていねいに", "narration": "根元から、ゆっくり入れていきます。"},
            {"key": "after_back", "frame": "back", "role": "仕上がり", "what": "仕上がりの後ろ姿", "how": "施術前と同じ位置・同じ高さから", "recommend": "video", "work": 5, "caption": "仕上がり", "narration": "仕上がりは、こんな感じです。"},
            {"key": "salon", "frame": "wide", "role": "場所", "what": "店内・セット面（人が写らないように）", "how": "縦向きで奥まで", "recommend": "photo", "work": 0, "optional": True, "caption": "", "narration": ""},
        ],
    },
    "process": {
        "label": "施術のこだわり",
        "goal": "信頼してもらう",
        "seconds": (20, 25),
        "bgm_categories": ["calm", "acoustic", "daily"],
        "cta": "フォロー",
        "slots": [
            {"key": "hero", "frame": "closeup", "role": "フック", "what": "仕上がり or 作業中の手元で一番きれいな瞬間", "how": "髪に寄って", "recommend": "video", "work": 5, "caption": "カラーの前に\n必ずすること", "narration": "カラーの前に、必ずやってることがあります。"},
            {"key": "consult", "frame": "hands", "role": "答え", "what": "カウンセリング・毛髪診断・カラーチャートの手元", "how": "手元に寄って", "recommend": "photo", "work": 1, "caption": "まず髪の状態を見る", "narration": "まず、髪の状態をちゃんと見ます。"},
            {"key": "mixing", "frame": "tools", "role": "こだわり", "what": "薬剤を調合している手元", "how": "真上から", "recommend": "video", "work": 2, "caption": "その人の髪で配合を変える", "narration": "配合は、その人の髪で毎回変えてます。"},
            {"key": "applying", "frame": "hands", "role": "手間", "what": "塗布・カットの手元", "how": "横から。手と髪が入るように", "recommend": "video", "work": 3, "caption": "ここだけは急がない", "narration": "ここだけは、急がないようにしてます。"},
            {"key": "check", "frame": "mirror", "role": "確認", "what": "鏡で確認している様子（顔が写らない角度）", "how": "鏡越しに髪だけ", "recommend": "photo", "work": 4, "caption": "最後にもう一度チェック", "narration": "最後にもう一回、全体を見ます。"},
        ],
    },
    "care_tips": {
        "label": "ホームケア豆知識",
        "goal": "保存・シェアしてもらう",
        "seconds": (15, 25),
        "bgm_categories": ["bright", "daily"],
        "cta": "保存",
        "slots": [
            {"key": "hero", "frame": "closeup", "role": "フック", "what": "ツヤのある毛先のアップ（結論が分かる所）", "how": "明るい所で", "recommend": "photo", "work": 1, "caption": "色持ちを良くする\n3つのこと", "narration": "カラーの色持ちを良くする方法、3つあります。"},
            {"key": "point1", "frame": "hands", "role": "ポイント1", "what": "シャンプーの手元・ボトル", "how": "手元に寄って", "recommend": "video", "work": 2, "caption": "① ぬるめのお湯で洗う", "narration": "一つ目、お湯は38度くらいのぬるめで。"},
            {"key": "point2", "frame": "hands", "role": "ポイント2", "what": "ドライヤーをかけている手元", "how": "横から", "recommend": "video", "work": 3, "caption": "② 根元から乾かす", "narration": "二つ目、乾かすときは根元から。"},
            {"key": "point3", "frame": "tools", "role": "ポイント3", "what": "アウトバストリートメント・おすすめの商品", "how": "斜め上から", "recommend": "photo", "work": 4, "caption": "③ 乾かす前にひと塗り", "narration": "三つ目、乾かす前に毛先にひと塗り。"},
        ],
    },
    "stylist_story": {
        "label": "スタイリストの思い",
        "goal": "ファンになってもらう",
        "seconds": (25, 35),
        "bgm_categories": ["emotional", "calm", "acoustic"],
        "cta": "フォロー",
        "slots": [
            {"key": "back", "frame": "back", "role": "フック", "what": "作業に向かうあなたの後ろ姿・手元", "how": "同僚に頼んで後ろから。顔は写さなくてOK", "recommend": "video", "work": 1, "caption": "最初は、なるつもり\nなかったんです", "narration": "最初は、美容師になるつもりなかったんです。"},
            {"key": "tools", "frame": "tools", "role": "過去", "what": "愛用のハサミ・コーム", "how": "真上から", "recommend": "photo", "work": 2, "caption": "10年目のハサミ", "narration": ""},
            {"key": "hands", "frame": "hands", "role": "転機", "what": "髪にふれている手元", "how": "手に寄って、ゆっくり", "recommend": "video", "work": 3, "caption": "変わったのは、あの一言", "narration": "変わったのは、お客様の一言でした。"},
            {"key": "salon", "frame": "wide", "role": "今", "what": "今の店内・セット面", "how": "縦向きで奥まで", "recommend": "photo", "work": 4, "caption": "今は、ここで", "narration": "今は、ここでやってます。"},
            {"key": "hero", "frame": "closeup", "role": "思い", "what": "仕上がりの毛先・ツヤ", "how": "髪に寄って", "recommend": "photo", "work": 5, "caption": "鏡を見た瞬間のために", "narration": "鏡を見た瞬間の顔のために、やってます。"},
        ],
    },
    "daily": {
        "label": "サロンの日常",
        "goal": "親近感",
        "seconds": (10, 20),
        "bgm_categories": ["daily", "lofi", "bright"],
        "cta": "フォロー",
        "slots": [
            {"key": "open", "frame": "wide", "role": "フック", "what": "開店前の店内・準備を始める瞬間", "how": "入口から奥に向けて", "recommend": "video", "work": 1, "caption": "開店前の1時間", "narration": "開店前の1時間、こんな感じです。"},
            {"key": "prep", "frame": "hands", "role": "準備", "what": "タオル・道具のセット", "how": "手元に寄って", "recommend": "video", "work": 2, "caption": "まずは道具のセット", "narration": "まずは道具をそろえて。"},
            {"key": "work", "frame": "hands", "role": "施術", "what": "施術中の手元", "how": "横から", "recommend": "video", "work": 3, "caption": "今日は一日カラー", "narration": "今日は、カラーの日です。"},
            {"key": "close", "frame": "wide", "role": "締め", "what": "片付け・夕方の店内", "how": "最初と同じ場所から", "recommend": "photo", "work": 4, "caption": "今日もおつかれさまでした", "narration": "今日も、おつかれさまでした。"},
        ],
    },
}

TEMPLATE_KEYS = list(TEMPLATES)
TEMPLATE_LABELS = {k: v["label"] for k, v in TEMPLATES.items()}

# 今日の施術メニュー → 向いている型
MENU_TO_TEMPLATE = [
    (("ブリーチ", "ハイライト", "インナー", "カラー", "白髪"), "before_after"),
    (("縮毛", "ストレート", "パーマ", "デジパ"), "before_after"),
    (("トリートメント", "髪質改善", "ヘッドスパ"), "process"),
    (("カット", "ボブ", "ショート"), "before_after"),
]

# 投稿の目的（テキスト投稿と共通）→ 型
PURPOSE_TO_TEMPLATE = {
    "nomination": "before_after",
    "weekday_daytime": "daily",
    "first_timer": "process",
    "repeat": "care_tips",
    "general": None,
}

ROTATION = ["before_after", "process", "care_tips", "daily", "stylist_story"]


def shot_list(template_key):
    slots = [dict(s) for s in TEMPLATES[template_key]["slots"]]
    return sorted(slots, key=lambda s: s["work"])


def choose_template(menu_items, recent_templates, purpose=None):
    """今日の施術メニュー・目的・直近の投稿から型を選ぶ。同じ型が3回続かないようにする。"""
    candidates = []
    if purpose and PURPOSE_TO_TEMPLATE.get(purpose):
        candidates.append(PURPOSE_TO_TEMPLATE[purpose])
    text = " ".join(menu_items or [])
    for keywords, key in MENU_TO_TEMPLATE:
        if any(k in text for k in keywords):
            candidates.append(key)
    if not candidates:
        recent_counts = {k: recent_templates[:5].count(k) for k in ROTATION}
        candidates = sorted(ROTATION, key=lambda k: (recent_counts.get(k, 0), ROTATION.index(k)))
    for key in candidates:
        if recent_templates[:2] != [key, key]:
            return key
    return candidates[0]


def theme_for(template_key, menu_items=None):
    menu = "・".join(menu_items or []) or "施術"
    return {
        "before_after": f"{menu}のビフォーアフター",
        "process": f"{menu}のこだわり",
        "care_tips": "ホームケアの豆知識",
        "stylist_story": "スタイリストの思い",
        "daily": "サロンの日常",
    }[template_key]


def frame_for(template_key, slot_key):
    for slot in TEMPLATES.get(template_key, {}).get("slots", []):
        if slot["key"] == slot_key:
            return slot.get("frame", "closeup")
    return "closeup"


FRAME_LABELS = {"closeup": "毛先・質感のアップ", "hands": "手元", "back": "後ろ姿", "mirror": "鏡越し（髪だけ）", "tools": "道具・薬剤", "wide": "店内・全景", "overhead": "真上から"}
