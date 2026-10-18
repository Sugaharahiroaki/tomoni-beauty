"""AIおまかせ：次に投稿すべき型をルールで採点し、理由を付ける。

スコア = 目的との相性 − 直近の偏り − 同じ型の連続 + 空き枠 × 予約導線 + 成果（件数で縮小）+ 好み + 採用率 − スキップ率
重みは settings.SNS_RECOMMEND_WEIGHTS（環境変数で上書き可）。理由文は定型文を組み立て、AIが使えるときだけ自然な文に整える。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.core.dates import today_local

from .post_types import POST_TYPES, PURPOSE_LABELS, TYPE_KEYS, TYPE_LABELS, missing_for

DEFAULT_WEIGHTS = {"purpose": 3.0, "bias": 4.0, "streak": 3.0, "availability": 2.0, "results": 2.0, "favorite": 1.0, "accept": 1.0, "skip": 1.5}
RECENT_WINDOW = 5
SHRINK_K = 3  # 縮小係数 = 件数 ÷ (件数 + K)。データが少ないうちは影響を小さく
AVAILABILITY_DAYS = 14
DEFAULT_WEEKLY_HOURS = 10.0


def weights() -> dict:
    return {**DEFAULT_WEIGHTS, **(getattr(settings, "SNS_RECOMMEND_WEIGHTS", None) or {})}


def shrink(n: int) -> float:
    return n / (n + SHRINK_K) if n else 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class Recommendation:
    post_type: str | None
    alternatives: list[str]
    scores: dict
    reason: str
    missing: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return TYPE_LABELS.get(self.post_type or "", "")

    @property
    def alternative_labels(self) -> list[str]:
        return [TYPE_LABELS[k] for k in self.alternatives]

    @property
    def needs(self) -> list[str]:
        return [n["label"] for n in POST_TYPES[self.post_type]["needs"]] if self.post_type else []

    @property
    def definition(self) -> dict:
        return POST_TYPES[self.post_type] if self.post_type else {}


# ------------------------------------------------------------------ 採点（純粋関数・テストしやすく）


def score_types(*, counts=None, purpose="general", recent_types=(), open_ratio=None, results_by_type=None, favorites=(), avoid=(), reactions_by_type=None, w=None) -> tuple[dict, dict]:
    """全ての型を採点する。counts が None（まだ撮っていない）のときは素材による除外をしない。"""
    w = w or weights()
    results_by_type = results_by_type or {}
    reactions_by_type = reactions_by_type or {}
    recent = list(recent_types)[:RECENT_WINDOW]
    total_n = sum(r["n"] for r in results_by_type.values())
    overall = (sum(r["avg"] * r["n"] for r in results_by_type.values()) / total_n) if total_n else 0.0
    scores, missing = {}, {}
    for key, t in POST_TYPES.items():
        excluded = None
        if counts is not None:
            miss = missing_for(key, counts)
            if miss:
                missing[key] = miss
                excluded = "素材が足りない"
        if key in avoid:
            excluded = excluded or "避けたい型"
        parts = {
            "purpose": w["purpose"] * t["purpose_fit"].get(purpose, 0.5),
            "bias": -w["bias"] * (recent.count(key) / len(recent)) if recent else 0.0,
            "streak": -w["streak"] if recent and recent[0] == key else 0.0,
            "availability": w["availability"] * open_ratio * t["booking"] if open_ratio else 0.0,
            "favorite": w["favorite"] if key in favorites else 0.0,
            "results": 0.0,
            "accept": 0.0,
            "skip": 0.0,
        }
        r = results_by_type.get(key)
        if r and r["n"] and overall > 0:
            parts["results"] = w["results"] * shrink(r["n"]) * _clamp(r["avg"] / overall - 1, -1, 1)
        rx = reactions_by_type.get(key)
        if rx and rx["n"]:
            parts["accept"] = w["accept"] * shrink(rx["n"]) * (rx["accepted"] / rx["n"] - 0.5)
            parts["skip"] = -w["skip"] * shrink(rx["n"]) * (rx["skipped"] / rx["n"])
        scores[key] = {"total": round(sum(parts.values()), 3), "parts": {k: round(v, 3) for k, v in parts.items()}, "excluded": excluded}
    return scores, missing


def rank(scores: dict) -> list[str]:
    """除外されていない型を点数順に。全部除外なら素材のいらない型、それも無ければ全部"""
    order = lambda keys: sorted(keys, key=lambda k: (-scores[k]["total"], TYPE_KEYS.index(k)))  # noqa: E731
    candidates = [k for k in TYPE_KEYS if not scores[k]["excluded"]]
    if not candidates:
        candidates = [k for k in TYPE_KEYS if not POST_TYPES[k]["needs"] and scores[k]["excluded"] != "避けたい型"] or list(TYPE_KEYS)
    return order(candidates)


def build_reason(best: str, scores: dict, purpose: str, recent: list[str], open_ratio) -> str:
    """加点・減点の大きい材料から1〜2文"""
    parts = scores[best]["parts"]
    label = TYPE_LABELS[best]
    sentences = []
    ordered = sorted(parts.items(), key=lambda kv: -abs(kv[1]))
    for name, value in ordered:
        if len(sentences) >= 2:
            break
        if name == "purpose" and value > 0 and purpose != "general":
            sentences.append(f"目的「{PURPOSE_LABELS.get(purpose, purpose)}」に合う型です")
        elif name == "availability" and value > 0:
            sentences.append("今後2週間は空き枠が多めなので、予約につながりやすい型を優先しました")
        elif name == "results" and value > 0:
            sentences.append("これまでの投稿で成果（保存・DM・予約クリック）が出ている型です")
        elif name == "favorite" and value > 0:
            sentences.append("よく使う型に設定されています")
        elif name == "accept" and value > 0:
            sentences.append("これまでの提案でよく採用されています")
    if recent and best not in recent[:RECENT_WINDOW] and len(sentences) < 2:
        sentences.append(f"直近{min(len(recent), RECENT_WINDOW)}件では使っていない型です")
    if recent and len(sentences) < 2:
        streak = recent[0]
        if streak != best and recent[:2].count(streak) == 2:
            sentences.append(f"直近は{TYPE_LABELS.get(streak, streak)}が続いています")
    if not sentences:
        sentences.append("見せ方を変えて、テーマは同じまま続けるのにちょうどいい型です")
    return f"{label}がおすすめです。" + "。".join(sentences[:2]) + "。"


# ------------------------------------------------------------------ 材料の収集


def asset_counts(assets) -> dict:
    counts = {"before": 0, "after": 0, "process": 0, "self": 0, "other": 0, "video": 0, "photo": 0}
    for a in assets:
        counts[a.role or "other"] = counts.get(a.role or "other", 0) + 1
        counts["video" if a.kind == "video" else "photo"] += 1
    return counts


def recent_types_for(stylist, exclude_post=None) -> list[str]:
    from .models import ReelPost

    qs = ReelPost.objects.filter(stylist=stylist).exclude(post_type="").exclude(status="SKIPPED")
    if exclude_post is not None:
        qs = qs.exclude(pk=exclude_post.pk)
    return list(qs.order_by("-created_at").values_list("post_type", flat=True)[:RECENT_WINDOW])


def open_ratio_for(stylist, today=None) -> float | None:
    """今後14日の空き時間 ÷ 週の稼働時間（空き枠を使っていない美容師は None）"""
    from apps.broadcasts.models import AvailabilitySlot

    if not AvailabilitySlot.objects.filter(stylist=stylist).exists():
        return None
    today = today or today_local()
    slots = AvailabilitySlot.objects.filter(stylist=stylist, status=AvailabilitySlot.Status.OPEN, date__gte=today, date__lt=today + timedelta(days=AVAILABILITY_DAYS))
    hours = float(sum(s.hours for s in slots))
    weekly = float(stylist.weekly_slot_hours or DEFAULT_WEEKLY_HOURS)
    return _clamp(hours / weekly, 0.0, 1.0) if weekly > 0 else None


def results_by_type_for(stylist) -> dict:
    from .models import ReelPost

    out: dict[str, dict] = {}
    for p in ReelPost.objects.filter(stylist=stylist, metrics_updated_at__isnull=False).exclude(post_type=""):
        s = p.manual_result_score or 0.0
        r = out.setdefault(p.post_type, {"n": 0, "sum": 0.0})
        r["n"] += 1
        r["sum"] += s
    return {k: {"n": r["n"], "avg": r["sum"] / r["n"]} for k, r in out.items()}


def reactions_by_type_for(stylist) -> dict:
    from .models import TypeRecommendation

    out: dict[str, dict] = {}
    for rec in TypeRecommendation.objects.filter(stylist=stylist).exclude(reaction="pending"):
        r = out.setdefault(rec.post_type, {"n": 0, "accepted": 0, "skipped": 0})
        r["n"] += 1
        if rec.reaction == "accepted":
            r["accepted"] += 1
        elif rec.reaction == "skipped":
            r["skipped"] += 1
    return out


def recommend_for(stylist, post=None, counts=None, extra_recent=(), today=None) -> Recommendation:
    """この美容師の次の投稿の型。post があればその素材で、無ければ素材の制約なし（今週のおすすめ）"""
    from .services import profile_of

    profile = profile_of(stylist)
    if counts is None and post is not None:
        counts = asset_counts(post.assets.all())
    recent = list(extra_recent) + recent_types_for(stylist, exclude_post=post)
    open_ratio = open_ratio_for(stylist, today)
    scores, missing = score_types(
        counts=counts,
        purpose=profile.purpose,
        recent_types=recent,
        open_ratio=open_ratio,
        results_by_type=results_by_type_for(stylist),
        favorites=profile.favorite_types or (),
        avoid=profile.avoid_types or (),
        reactions_by_type=reactions_by_type_for(stylist),
    )
    ranked = rank(scores)
    best = ranked[0] if ranked else None
    reason = build_reason(best, scores, profile.purpose, recent, open_ratio) if best else ""
    reason = polish_reason(reason)
    return Recommendation(post_type=best, alternatives=ranked[1:3], scores=scores, reason=reason, missing=missing, context={"counts": counts, "purpose": profile.purpose, "recent": recent[:RECENT_WINDOW], "open_ratio": open_ratio})


def polish_reason(text: str) -> str:
    """AIが使えるときだけ、理由文を自然な日本語に整える（失敗したら定型文のまま）"""
    if settings.AI_FAKE or not text:
        return text
    from apps.ai.claude_client import AIError, get_ai

    schema = {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"], "additionalProperties": False}
    system = "あなたは美容師向けアプリのアシスタントです。渡された「おすすめの理由」を、意味を変えずに自然でやわらかい日本語（2文・80字以内）に整えてください。新しい事実や数字は足さないでください。"
    try:
        result = get_ai().generate_json("recommend_reason", system, text, schema, max_tokens=300)
        polished = (result or {}).get("reason", "").strip()
        return polished if 0 < len(polished) <= 120 else text
    except AIError:
        return text


def record(stylist, rec: Recommendation, post=None):
    from .models import TypeRecommendation

    if rec.post_type is None:
        return None
    return TypeRecommendation.objects.create(stylist=stylist, post=post, post_type=rec.post_type, alternatives=rec.alternatives, scores=rec.scores, reason=rec.reason, missing=rec.missing, context=rec.context)


# ------------------------------------------------------------------ 今週のおすすめ


def week_bounds(today=None) -> tuple:
    today = today or today_local()
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=7)


def week_count(stylist, today=None) -> int:
    from apps.core.dates import local_date_range_to_datetimes

    from .models import ReelPost

    start, end = week_bounds(today)
    start_dt, end_dt = local_date_range_to_datetimes(start, end)
    return ReelPost.objects.filter(stylist=stylist, created_at__gte=start_dt, created_at__lt=end_dt).exclude(post_type="").exclude(status="SKIPPED").count()


def weekly_plan(stylist, today=None) -> list[Recommendation]:
    """今週あと何本作るか（週の本数 − 今週作った本数）だけ提案する。1本目を直近に加えて2本目を計算する"""
    from .services import profile_of

    profile = profile_of(stylist)
    remaining = max(int(profile.posts_per_week or 0) - week_count(stylist, today), 0)
    plan: list[Recommendation] = []
    planned: list[str] = []
    for _ in range(min(remaining, 7)):
        rec = recommend_for(stylist, counts=None, extra_recent=planned, today=today)
        if rec.post_type is None:
            break
        plan.append(rec)
        planned.insert(0, rec.post_type)
    return plan


# ------------------------------------------------------------------ テーマ（得意な悩み）


def _ngrams(text: str, n: int = 2) -> set[str]:
    cleaned = "".join(ch for ch in (text or "") if ch not in "・、。,.　 ()（）/／")
    return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}


def _overlap(a: str, b: str) -> bool:
    return bool(_ngrams(a) & _ngrams(b))


def choose_theme(stylist, post=None) -> str:
    """得意な悩みのどれか。施術記録の悩みに近いものがあればそれ、無ければ最近いちばん使っていないもの"""
    from .models import ReelPost
    from .services import profile_of

    concerns = [c for c in (profile_of(stylist).focus_concerns or []) if c]
    if not concerns:
        return ""
    if post is not None and post.karte_id:
        safe = post.karte.sns_safe_fields()
        texts = list(safe.get("concerns") or []) + [safe.get("treatment_summary", ""), safe.get("results", "")]
        for c in concerns:
            if any(_overlap(c, t) for t in texts if t):
                return c
    qs = ReelPost.objects.filter(stylist=stylist).exclude(theme="").exclude(status="SKIPPED")
    if post is not None:
        qs = qs.exclude(pk=post.pk)
    recent = list(qs.order_by("-created_at").values_list("theme", flat=True)[:30])
    never = [c for c in concerns if c not in recent]
    if never:
        return never[0]
    return max(concerns, key=lambda c: recent.index(c))
