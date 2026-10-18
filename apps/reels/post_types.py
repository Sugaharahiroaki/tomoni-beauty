"""SNS投稿の「型」（5つ）。

使う人に見せるのはこの5つだけ。動画の撮り方（recipes.py の7つの構成）は型の中に隠す。
出来上がる形（動画／フィード複数枚／ストーリーズ）は、入れた素材で決まる：動画が1本でもあれば動画。
"""
from __future__ import annotations

PURPOSES = [
    ("nomination", "指名を増やしたい"),
    ("weekday_daytime", "平日昼を埋めたい"),
    ("first_timer", "初めての人の不安を減らす"),
    ("repeat", "再来店につなげる"),
    ("general", "特に決めない"),
]
PURPOSE_LABELS = dict(PURPOSES)

FORMATS = [("reel", "動画"), ("feed", "フィード（複数枚）"), ("stories", "ストーリーズ")]
FORMAT_LABELS = dict(FORMATS)

ROLES = [("before", "ビフォー"), ("after", "アフター"), ("process", "施術中"), ("self", "本人"), ("other", "その他")]
ROLE_LABELS = dict(ROLES)

HOOK_TYPES = [
    ("call", "呼びかけ", "「〜で悩んでいる人へ」と、見てほしい人に直接声をかける"),
    ("result", "結果先出し", "仕上がりや効果を先に言い切る"),
    ("scene", "悩みの映像", "悩んでいる場面を一言で描く（朝の鏡の前、など）"),
    ("surprise", "意外性", "思い込みをひっくり返す一言"),
    ("local", "地域", "地名を入れて近所の人に届ける"),
]
HOOK_TYPE_LABELS = {k: label for k, label, _ in HOOK_TYPES}

# 型ごとの定義
#  needs: [{"any": [役割...], "min": n, "label": "足りないときの表示"}]  … "video" は役割に関係なく動画
#  purpose_fit: 目的との相性 0〜1 / booking: 予約導線の強さ 0〜1
POST_TYPES = {
    "before_after": {
        "label": "ビフォーアフター",
        "tagline": "悩み → 結果",
        "goal": "指名・予約",
        "description": "施術前と後を見せて、同じ悩みの人に「ここなら変わる」と伝える。",
        "primary_format": "reel",
        "photo_only_format": "reel",
        "needs": [
            {"any": ["after"], "min": 1, "label": "アフター（仕上がり）の写真を1枚"},
            {"any": ["before", "video"], "min": 1, "label": "ビフォーの写真か、施術中の動画を1つ"},
        ],
        "compositions": ["before_after"],
        "purpose_fit": {"nomination": 1.0, "weekday_daytime": 0.9, "first_timer": 0.5, "repeat": 0.4, "general": 0.6},
        "booking": 1.0,
        "hook_types": ["call", "result", "scene"],
        "icon": "🔁",
    },
    "process_reel": {
        "label": "工程リール",
        "tagline": "手元と髪の動き",
        "goal": "信頼・初めての人",
        "description": "カット・シャンプー・塗布の様子を見せて、丁寧さと雰囲気を伝える。",
        "primary_format": "reel",
        "photo_only_format": "reel",
        "needs": [{"any": ["video"], "min": 1, "label": "施術中の動画を1本（カット・シャンプー・塗布など）"}],
        "compositions": ["process"],
        "purpose_fit": {"nomination": 0.7, "weekday_daytime": 0.5, "first_timer": 0.9, "repeat": 0.3, "general": 0.6},
        "booking": 0.6,
        "hook_types": ["surprise", "scene", "call"],
        "icon": "✂️",
    },
    "suggestion": {
        "label": "似合わせ提案（作品集）",
        "tagline": "得意なデザインを一度に",
        "goal": "保存・指名",
        "description": "仕上がり写真を並べて「この人に頼むとこうなる」を一目で伝える。",
        "primary_format": "feed",
        "photo_only_format": "feed",
        "needs": [{"any": ["after"], "min": 2, "label": "アフター（仕上がり）の写真を2枚以上"}],
        "compositions": ["color_catalog"],
        "purpose_fit": {"nomination": 0.8, "weekday_daytime": 0.7, "first_timer": 0.6, "repeat": 0.6, "general": 0.6},
        "booking": 0.7,
        "hook_types": ["result", "call", "local"],
        "icon": "🎨",
    },
    "tips": {
        "label": "お役立ち",
        "tagline": "悩み解決のコツ",
        "goal": "保存・再来",
        "description": "ホームケアや選び方のコツ。保存してもらい、思い出したときに来てもらう。",
        "primary_format": "feed",
        "photo_only_format": "feed",
        "needs": [],
        "compositions": ["care_tips"],
        "purpose_fit": {"nomination": 0.4, "weekday_daytime": 0.3, "first_timer": 0.6, "repeat": 1.0, "general": 0.6},
        "booking": 0.3,
        "hook_types": ["surprise", "call", "result"],
        "icon": "💡",
    },
    "personality": {
        "label": "人柄・考え方",
        "tagline": "この人に頼みたい",
        "goal": "ファン化・初めての人",
        "description": "美容師になった理由や大事にしていること。顔と声が見えると初めての人の不安が減る。",
        "primary_format": "stories",
        "photo_only_format": "stories",
        "needs": [],
        "compositions": ["stylist_story", "self_intro", "daily"],
        "purpose_fit": {"nomination": 0.6, "weekday_daytime": 0.3, "first_timer": 1.0, "repeat": 0.4, "general": 0.5},
        "booking": 0.3,
        "hook_types": ["surprise", "scene", "local"],
        "icon": "🙂",
    },
}
TYPE_KEYS = list(POST_TYPES)
TYPE_LABELS = {k: v["label"] for k, v in POST_TYPES.items()}
TYPE_CHOICES = [(k, v["label"]) for k, v in POST_TYPES.items()]

# 素材の役割 → 構成ごとの撮影リスト項目（先に挙げたものから順に埋める。足りなければ最後の項目に重ねる）
ROLE_SLOTS = {
    "before_after": {"after": ["after_hero", "after_back"], "before": ["before"], "process": ["hands", "bowl"], "self": ["hands"], "other": ["salon", "bowl"]},
    "process": {"process": ["applying", "mixing", "check", "consult"], "after": ["hero"], "before": ["consult"], "self": ["consult", "check"], "other": ["check"]},
    "color_catalog": {"after": ["hero", "work1", "work2", "work3", "work4", "work5", "work6", "closing"], "before": ["closing"], "process": ["closing"], "self": ["closing"], "other": ["closing"]},
    "care_tips": {"after": ["hero"], "process": ["point1", "point2", "point3"], "self": ["point1", "point2"], "other": ["point3"], "before": ["point1"]},
    "stylist_story": {"self": ["back", "smile", "hands", "salon"], "process": ["hands", "salon", "tools"], "after": ["hero"], "other": ["tools", "salon"], "before": ["tools"]},
    "self_intro": {"self": ["greeting", "counsel", "work", "finish"], "process": ["work", "finish", "counsel"], "after": ["works"], "other": ["counsel"], "before": ["works"]},
    "daily": {"self": ["open", "counsel", "work", "blow", "close"], "process": ["work", "blow", "prep"], "after": ["works"], "other": ["prep", "close"], "before": ["works"]},
}

# 役割ごとの撮影ガイド（足りない素材をその場で撮るとき）
ROLE_GUIDES = {
    "before": {"frame": "back", "mode": "photo", "what": "施術前の後ろ姿・毛先", "how": "後ろから。首より上は入れなくてOK"},
    "after": {"frame": "back", "mode": "photo", "what": "仕上がりの後ろ姿か毛先", "how": "施術前と同じ位置・同じ高さから。顔は入れない"},
    "process": {"frame": "hands", "mode": "video", "what": "施術中の手元（カット・シャンプー・塗布）", "how": "少し横から。手と髪が真ん中に。3秒で止まります"},
    "self": {"frame": "person", "mode": "video", "what": "あなた自身（胸から上）", "how": "明るい所で。あいさつや作業中の表情"},
    "video": {"frame": "hands", "mode": "video", "what": "施術中の動画", "how": "少し横から。手と髪が真ん中に。3秒で止まります"},
}


def missing_for(post_type: str, counts: dict) -> list[str]:
    """型に必要な素材のうち足りないものの表示（空なら作れる）"""
    out = []
    for need in POST_TYPES[post_type]["needs"]:
        have = sum(counts.get(role, 0) for role in need["any"])
        if have < need["min"]:
            out.append(need["label"])
    return out


def missing_roles_for(post_type: str, counts: dict) -> list[str]:
    """足りない素材の役割（撮影ガイドを開くため）。need の先頭の役割を返す"""
    out = []
    for need in POST_TYPES[post_type]["needs"]:
        have = sum(counts.get(role, 0) for role in need["any"])
        if have < need["min"]:
            out.append(need["any"][0])
    return out


def decide_format(post_type: str, counts: dict) -> str:
    """出来上がる形。動画が1本でもあれば動画。写真だけなら型ごとの形"""
    if counts.get("video", 0) > 0:
        return "reel"
    return POST_TYPES[post_type]["photo_only_format"]


def composition_for(post_type: str, counts: dict, has_intro: bool = False) -> str:
    """動画にするときの構成（recipes.py の型キー）"""
    comps = POST_TYPES[post_type]["compositions"]
    if post_type != "personality":
        return comps[0]
    if counts.get("self", 0) >= 1 and not has_intro:
        return "self_intro"
    if counts.get("self", 0) >= 3:
        return "daily"
    return "stylist_story"


def type_for_composition(template_key: str) -> str:
    for key, t in POST_TYPES.items():
        if template_key in t["compositions"]:
            return key
    return ""
