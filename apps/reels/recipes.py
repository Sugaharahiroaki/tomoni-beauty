"""投稿の型（美容師向け・7つ）と、型ごとの撮影リスト。

features は主役：customer＝お客様の髪（顔出しは顧客の同意に従う。顧客なしなら不可）/ stylist＝美容師本人（本人の顔は可）。

frame は構図の型（カメラのガイド線に使う）：
closeup＝毛先・質感のアップ / person＝本人（胸から上） / hands＝手元 / back＝後ろ姿 / mirror＝鏡越し / tools＝道具・薬剤 / wide＝店内 / overhead＝真上

{お客様} はそのまま。お客様の顔は「顔出しOK」のときだけ写してよい（既定は後ろ姿・手元）。
"""

TEMPLATES = {
    "before_after": {
        "features": "customer",
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
        "features": "customer",
        "label": "施術のこだわり",
        "goal": "信頼してもらう",
        "seconds": (20, 25),
        "bgm_categories": ["calm", "acoustic", "daily"],
        "cta": "フォロー",
        "slots": [
            {"key": "hero", "frame": "closeup", "role": "フック", "what": "仕上がり or 作業中の手元で一番きれいな瞬間", "how": "髪に寄って", "recommend": "video", "work": 5, "caption": "カラーの前に\nいつもすること", "narration": "カラーの前に、いつもやってることがあります。"},
            {"key": "consult", "frame": "hands", "role": "答え", "what": "カウンセリング・毛髪診断・カラーチャートの手元", "how": "手元に寄って", "recommend": "photo", "work": 1, "caption": "まず髪の状態を見る", "narration": "まず、髪の状態をちゃんと見ます。"},
            {"key": "mixing", "frame": "tools", "role": "こだわり", "what": "薬剤を調合している手元", "how": "真上から", "recommend": "video", "work": 2, "caption": "その人の髪で配合を変える", "narration": "配合は、その人の髪で毎回変えてます。"},
            {"key": "applying", "frame": "hands", "role": "手間", "what": "塗布・カットの手元", "how": "横から。手と髪が入るように", "recommend": "video", "work": 3, "caption": "ここだけは急がない", "narration": "ここだけは、急がないようにしてます。"},
            {"key": "check", "frame": "mirror", "role": "確認", "what": "鏡で確認している様子（顔が写らない角度）", "how": "鏡越しに髪だけ", "recommend": "photo", "work": 4, "caption": "最後にもう一度チェック", "narration": "最後にもう一回、全体を見ます。"},
        ],
    },
    "care_tips": {
        "features": "customer",
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
        "features": "stylist",
        "seconds": (25, 35),
        "bgm_categories": ["emotional", "calm", "acoustic"],
        "cta": "フォロー",
        "slots": [
            {"key": "back", "frame": "back", "role": "フック", "what": "出勤する・作業に向かうあなたの後ろ姿", "how": "同僚に頼んで後ろから。振り返る程度ならOK", "recommend": "video", "work": 1, "caption": "最初は、美容師に\nなるつもりなかったんです", "narration": "最初は、美容師になるつもり、なかったんです。"},
            {"key": "tools", "frame": "tools", "role": "過去", "what": "愛用のハサミ・コームを並べる手元", "how": "真上か斜め上から", "recommend": "video", "work": 2, "caption": "きっかけは\n家族の髪を切ったこと", "narration": "きっかけは、家族の髪を切ったことでした。"},
            {"key": "hands", "frame": "hands", "role": "転機", "what": "仕上げで髪にふれている手元", "how": "手に寄って、ゆっくり。お客様は後ろ姿", "recommend": "video", "work": 3, "caption": "鏡を見て笑ってくれた顔が\n忘れられなくて", "narration": "鏡を見て笑ってくれた顔が、忘れられなくて。"},
            {"key": "salon", "frame": "wide", "role": "今", "what": "今のサロンで施術している様子（ブロー・調合など）", "how": "縦向きで。お客様は後ろ姿", "recommend": "video", "work": 4, "caption": "だから今は\n3週間後の髪まで考える", "narration": "だから今は、三週間後の髪まで考えて、やっています。"},
            {"key": "hero", "frame": "closeup", "role": "作品", "what": "仕上がりの写真（1〜2枚）", "how": "後ろ姿か毛先。掲載OKの写真だけ", "recommend": "photo", "work": 0, "caption": "伸びても、色が落ちても\nきれいなように", "narration": "伸びても、色が落ちても、きれいなように。"},
            {"key": "smile", "frame": "person", "role": "思い", "what": "あなたがカメラに向かって笑うところ", "how": "胸から上。最後に軽く会釈", "recommend": "video", "work": 5, "optional": True, "caption": "鏡を見た瞬間のために", "narration": "鏡を見た瞬間の顔のために、やってます。"},
        ],
    },
    "daily": {
        "label": "スタイリストの1日",
        "goal": "親近感（フォロー）",
        "features": "stylist",
        "seconds": (15, 25),
        "bgm_categories": ["lofi", "daily", "bright"],
        "cta": "フォロー",
        "slots": [
            {"key": "open", "frame": "back", "role": "フック", "what": "出勤・お店に入るところ（朝の街でもOK）", "how": "後ろから。振り返って笑うと◎", "recommend": "video", "work": 1, "caption": "{エリア}の美容師の1日", "narration": "{エリア}で働く美容師の、一日です。"},
            {"key": "prep", "frame": "hands", "role": "準備", "what": "開店前の準備（道具のセット・タオル）", "how": "手元に寄って", "recommend": "video", "work": 2, "caption": "開店前の準備", "narration": "開店前は、道具のセットから。"},
            {"key": "counsel", "frame": "hands", "role": "カウンセリング", "what": "カウンセリングの様子", "how": "お客様は後ろ姿で。あなたの表情と手元", "recommend": "video", "work": 3, "caption": "まずはカウンセリング", "narration": "一人目のお客様。まずはカウンセリング。"},
            {"key": "work", "frame": "hands", "role": "施術", "what": "カラーの調合・カットの手元", "how": "横から", "recommend": "video", "work": 4, "caption": "カラーとカット", "narration": "お昼は、カラーとカット。"},
            {"key": "blow", "frame": "back", "role": "仕上げ", "what": "仕上げのブロー", "how": "お客様の後ろから", "recommend": "video", "work": 5, "caption": "仕上げのブロー", "narration": "夕方は、仕上げのブロー。"},
            {"key": "works", "frame": "back", "role": "今日の仕上がり", "what": "今日の仕上がり写真（2〜3枚）", "how": "掲載OKの写真だけ", "recommend": "photo", "work": 6, "optional": True, "caption": "今日の仕上がり", "narration": "今日の仕上がりは、こんな感じ。"},
            {"key": "close", "frame": "wide", "role": "締め", "what": "片付け・夕方の店内", "how": "最初と同じ場所から", "recommend": "video", "work": 7, "caption": "今日も\nおつかれさまでした", "narration": "今日も、おつかれさまでした。"},
        ],
    },
    "self_intro": {
        "label": "自己紹介",
        "goal": "初めての人に人柄を知ってもらい、指名につなげる",
        "features": "stylist",
        "seconds": (15, 25),
        "bgm_categories": ["bright", "daily", "acoustic"],
        "cta": "予約",
        "slots": [
            {"key": "greeting", "frame": "person", "role": "フック", "what": "あなたがカメラに向かってあいさつ・手を振るところ", "how": "胸から上。セット面の前の明るい所で、5秒くらい回す", "recommend": "video", "work": 1, "caption": "はじめまして\n{サロン}の{名前}です", "narration": "はじめまして。{サロン}でスタイリストをしている、{名前}です。"},
            {"key": "works", "frame": "back", "role": "得意", "what": "得意なスタイルの仕上がり写真（2〜4枚）", "how": "お客様の後ろ姿・毛先。掲載OKの写真だけ", "recommend": "photo", "work": 0, "caption": "得意なのは\n{得意}", "narration": "得意なのは、{得意}です。"},
            {"key": "counsel", "frame": "hands", "role": "こだわり", "what": "カウンセリングの様子（タブレット・カラーチャート）", "how": "お客様は後ろ姿で。あなたの表情と手元が入るように", "recommend": "video", "work": 2, "caption": "最初に聞くのは\n「なりたくない髪」", "narration": "最初にいつも聞くのは、なりたくない髪のことです。"},
            {"key": "work", "frame": "hands", "role": "施術", "what": "カット・塗布している手元", "how": "少し横から。手と髪が真ん中に", "recommend": "video", "work": 3, "caption": "そこに一番\n本音が出るから", "narration": "そこに、いちばん本音が出るので。"},
            {"key": "finish", "frame": "back", "role": "締め", "what": "仕上げで髪にふれているところ", "how": "お客様の後ろから。顔は入れない", "recommend": "video", "work": 4, "caption": "鏡を見た瞬間\n笑ってもらえたら", "narration": "鏡を見た瞬間、笑ってもらえたら、うれしいです。"},
        ],
    },
    "color_catalog": {
        "label": "作品集（○選）",
        "goal": "保存・指名（得意なデザインを一度に見せる）",
        "features": "customer",
        "seconds": (15, 25),
        "bgm_categories": ["lofi", "bright", "daily"],
        "cta": "予約",
        "slots": [
            {"key": "hero", "frame": "back", "role": "フック", "what": "一番目を引く仕上がり（2枚あると良い）", "how": "後ろ姿か毛先。明るい所で", "recommend": "photo", "work": 0, "caption": "ブリーチで、ここまで変わる", "narration": "ブリーチで出せる色、ぜんぶ見せます。"},
            {"key": "work1", "frame": "back", "role": "①", "what": "作品1（仕上がりの後ろ姿・横）", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "caption": "① くすみピンク", "narration": "ひとつめ、くすみピンク。"},
            {"key": "work2", "frame": "back", "role": "②", "what": "作品2", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "caption": "② コッパーオレンジ", "narration": "ふたつめ、コッパーオレンジ。"},
            {"key": "work3", "frame": "back", "role": "③", "what": "作品3", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "caption": "③ ネイビー", "narration": "みっつめ、ネイビー。"},
            {"key": "work4", "frame": "back", "role": "④", "what": "作品4", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "optional": True, "caption": "④ 裾だけブルー", "narration": "よっつめ、裾だけブルー。"},
            {"key": "work5", "frame": "back", "role": "⑤", "what": "作品5", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "optional": True, "caption": "⑤ ホワイトブロンド", "narration": "いつつめ、ホワイトブロンド。"},
            {"key": "work6", "frame": "back", "role": "⑥", "what": "作品6", "how": "掲載OKのお客様だけ。顔は入れない", "recommend": "photo", "work": 0, "optional": True, "caption": "⑥ ミルクティーベージュ", "narration": "むっつめ、ミルクティーベージュ。"},
            {"key": "closing", "frame": "back", "role": "締め", "what": "いちばん提案したいスタイル（例: 伸びても自然なハイライト）", "how": "後ろ姿", "recommend": "photo", "work": 0, "optional": True, "caption": "伸びても自然がいい人は\nハイライト", "narration": "伸びても自然がいい人は、ハイライトがおすすめです。"},
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
    "first_timer": "self_intro",
    "repeat": "care_tips",
    "general": None,
}

ROTATION = ["before_after", "process", "care_tips", "daily", "stylist_story", "self_intro", "color_catalog"]


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
        "daily": "スタイリストの1日",
        "self_intro": "はじめまして（自己紹介）",
        "color_catalog": f"{menu if menu_items else 'デザインカラー'}の作品集",
    }[template_key]


def frame_for(template_key, slot_key):
    for slot in TEMPLATES.get(template_key, {}).get("slots", []):
        if slot["key"] == slot_key:
            return slot.get("frame", "closeup")
    return "closeup"


FRAME_LABELS = {"closeup": "毛先・質感のアップ", "person": "本人（胸から上）", "hands": "手元", "back": "後ろ姿", "mirror": "鏡越し（髪だけ）", "tools": "道具・薬剤", "wide": "店内・全景", "overhead": "真上から"}


def features_stylist(template_key) -> bool:
    """本人が主役の型か（顧客なしの投稿で本人の顔を写してよいか）"""
    return TEMPLATES.get(template_key, {}).get("features") == "stylist"

