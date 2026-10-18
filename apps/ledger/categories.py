"""経費科目（青色申告決算書の科目に対応）と勘定科目。

※「これは経費になる」とは断定しない。科目は記録の整理用で、最終判断は税理士に確認する前提。
"""
from __future__ import annotations

# code, 表示名, ヒント, 勘定科目名（決算書の科目）, 決算書での区分（cogs=売上原価 / expense=経費）
EXPENSE_CATEGORIES = [
    ("materials", "材料費（仕入）", "カラー剤・薬剤・シャンプー等の施術材料", "仕入高", "cogs"),
    ("booth_rent", "面貸し料・場所代", "サロンへ支払う席料・場所代", "地代家賃", "expense"),
    ("supplies", "消耗品費", "タオル・手袋・小物・10万円未満の器具", "消耗品費", "expense"),
    ("travel", "旅費交通費", "電車・タクシー・講習会への移動", "旅費交通費", "expense"),
    ("communication", "通信費", "スマホ・ネット（私用分は按分）", "通信費", "expense"),
    ("advertising", "広告宣伝費", "SNS広告・名刺・ホットペッパー掲載料", "広告宣伝費", "expense"),
    ("entertainment", "接待交際費", "お客様・同業との飲食・手土産", "接待交際費", "expense"),
    ("training", "研修費", "セミナー・講習・教材", "研修費", "expense"),
    ("fees", "支払手数料", "振込手数料・決済手数料・アプリ利用料", "支払手数料", "expense"),
    ("insurance", "損害保険料", "賠償責任保険など", "損害保険料", "expense"),
    ("repairs", "修繕費", "器具の修理", "修繕費", "expense"),
    ("utilities", "水道光熱費", "自宅サロン等（按分）", "水道光熱費", "expense"),
    ("taxes", "租税公課", "個人事業税・収入印紙など", "租税公課", "expense"),
    ("depreciation", "減価償却費", "10万円以上の器具（年末に計上）", "減価償却費", "expense"),
    ("outsourcing", "外注工賃", "撮影・デザインの外注", "外注工賃", "expense"),
    ("misc", "雑費", "その他", "雑費", "expense"),
]

CATEGORY_CHOICES = [(c[0], c[1]) for c in EXPENSE_CATEGORIES]
CATEGORY_BY_CODE = {c[0]: {"code": c[0], "label": c[1], "hint": c[2], "account": c[3], "section": c[4]} for c in EXPENSE_CATEGORIES}


def category_label(code: str) -> str:
    return CATEGORY_BY_CODE.get(code, {}).get("label", code)


def category_account(code: str) -> str:
    return CATEGORY_BY_CODE.get(code, {}).get("account", "雑費")


def category_section(code: str) -> str:
    return CATEGORY_BY_CODE.get(code, {}).get("section", "expense")


# 報酬明細の控除項目ラベル → 科目
DEDUCTION_KEYWORDS = [
    (("材料", "薬剤", "商材", "仕入"), "materials"),
    (("場所", "面貸", "席料", "家賃", "ブース", "使用料"), "booth_rent"),
    (("振込", "手数料", "決済"), "fees"),
    (("広告", "掲載", "ホットペッパー", "HPB"), "advertising"),
    (("消耗", "タオル"), "supplies"),
    (("保険",), "insurance"),
    (("研修", "講習"), "training"),
]


def deduction_category(label: str) -> str:
    text = label or ""
    for keywords, code in DEDUCTION_KEYWORDS:
        if any(k.lower() in text.lower() for k in keywords):
            return code
    return "misc"


# 勘定科目（複式簿記）
ACCOUNTS = {
    # 資産
    "現金": "asset",
    "普通預金": "asset",
    "売掛金": "asset",
    "事業主貸": "drawing",
    # 負債・資本
    "事業主借": "equity",
    "元入金": "equity",
    # 収益
    "売上高": "revenue",
    "雑収入": "revenue",
    # 売上原価
    "仕入高": "cogs",
}
for _c in EXPENSE_CATEGORIES:
    if _c[4] == "expense":
        ACCOUNTS[_c[3]] = "expense"

DEBIT_NORMAL = {"asset", "drawing", "expense", "cogs"}
ACCOUNT_ORDER = list(ACCOUNTS.keys())
