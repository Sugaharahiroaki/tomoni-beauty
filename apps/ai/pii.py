"""個人情報チェック（決定論的な層）。LLMによるチェックの前段として必ず通す。"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# 名前として扱う最小長（1文字の姓・名は誤検知が多すぎるので除外）
MIN_NAME_LEN = 2

PATTERNS = {
    "age": re.compile(r"(?<![\d０-９])([1-9１-９]?[0-9０-９])\s*(歳|才|代後半|代前半|代半ば)"),
    "phone": re.compile(r"(?<!\d)0\d{1,4}[-‐ー−]?\d{1,4}[-‐ー−]?\d{3,4}(?!\d)"),
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "postal": re.compile(r"〒?\s?\d{3}[-‐ー−]\d{4}"),
    "line_id": re.compile(r"(?i)(?:LINE\s*ID|ライン\s*ID)\s*[:：]?\s*@?[\w.-]{3,}"),
    # 「山田さんが」「はなこちゃんは」など、敬称の直後に助詞が続くケースも拾う（漢字・カナが続く「様子」などは除外）
    "honorific_name": re.compile(r"([一-龥ぁ-んァ-ヶ]{2,6}?)(さん|様|さま|ちゃん|くん)(?![一-龥ァ-ヶ])"),
}

# 投稿に出すべきでない私生活ワード（警告扱い。禁止ではなく確認を促す）
SENSITIVE_WORDS = [
    "離婚", "妊娠", "出産", "不妊", "病気", "入院", "手術", "うつ", "借金", "転職", "退職", "失業", "受験", "浮気", "介護", "葬式", "通院", "年収", "給料", "住んで", "在住", "勤務先", "会社名",
]

GENERIC_HONORIFIC_WORDS = {
    "お客様", "お客さま", "お客さん", "みなさん", "皆さん", "皆さま", "奥様", "奥さん", "旦那さん", "お母さん", "お父さん", "お姉さん", "お兄さん",
    "子供さん", "お子さん", "お子様", "常連さん", "美容師さん", "スタッフさん", "担当さん", "初めてさん", "はじめてさん", "新規さん", "リピーターさん",
    "赤ちゃん", "おばあちゃん", "おじいちゃん", "お嬢さん", "息子さん", "娘さん", "友達さん", "ご主人様",
}


@dataclass
class PiiFinding:
    kind: str
    text: str
    severity: str = "error"  # error | warning


@dataclass
class PiiResult:
    findings: list[PiiFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[PiiFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[PiiFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [{"kind": f.kind, "text": f.text, "severity": f.severity} for f in self.findings],
        }


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def name_variants(*names: str | None) -> set[str]:
    """顧客名から検出対象のバリエーションを作る（姓・名の分割、空白除去など）。"""
    variants: set[str] = set()
    for raw in names:
        if not raw:
            continue
        n = normalize(raw).strip()
        if not n:
            continue
        candidates = {n, n.replace(" ", "")}
        for part in re.split(r"[\s　・/／]+", n):
            if part:
                candidates.add(part)
        for c in candidates:
            if len(c) >= MIN_NAME_LEN:
                variants.add(c)
    return variants


def find_forbidden_terms(text: str, terms: set[str] | list[str]) -> list[str]:
    body = normalize(text)
    hits = []
    for term in sorted(set(terms), key=len, reverse=True):
        if term and term in body:
            hits.append(term)
    return hits


def check_text(text: str, forbidden_terms: set[str] | list[str] | None = None) -> PiiResult:
    """SNS投稿文の個人情報チェック。

    - 顧客名（姓・名・読み）が含まれていたら error
    - 年齢・電話・メール・郵便番号・LINE ID は error
    - 「○○さん」のような呼びかけは、一般名詞を除いて error
    - 私生活ワードは warning
    """
    result = PiiResult()
    body = normalize(text)
    if not body:
        return result

    for term in find_forbidden_terms(body, forbidden_terms or []):
        result.findings.append(PiiFinding("customer_name", term))

    for kind in ("age", "phone", "email", "postal", "line_id"):
        for m in PATTERNS[kind].finditer(body):
            result.findings.append(PiiFinding(kind, m.group(0)))

    # 「○○さん」は一般名詞（お客様・常連さん等）を除き、確認を促す warning にする。
    # 顧客名そのものは上の customer_name チェックで error になる。
    for m in PATTERNS["honorific_name"].finditer(body):
        whole = m.group(0)
        if any(g in whole for g in GENERIC_HONORIFIC_WORDS):
            continue
        result.findings.append(PiiFinding("named_person", whole, severity="warning"))

    for word in SENSITIVE_WORDS:
        if word in body:
            result.findings.append(PiiFinding("sensitive_topic", word, severity="warning"))

    return result
