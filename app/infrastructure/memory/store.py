"""会话片段（一个话题）的存储与混合检索。

检索 = 向量（bge-small-zh）+ BM25（jieba）+ 时间偏好 + 标签加成，
最后做一层去重（同义片段只留最相关的一条），避免预算被重复内容吃满。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from ...config import SEGMENT_RETRIEVE_TOP_K

VECTOR_WEIGHT = 0.50
BM25_WEIGHT = 0.25
RECENCY_WEIGHT = 0.12
TAG_WEIGHT = 0.13
UPDATE_RECENCY_WEIGHT = 0.30
DEDUP_THRESHOLD = 0.6

RECENT_WORDS = ("现在", "目前", "如今", "当前", "最新", "进展", "搬", "涨", "几岁")


@dataclass
class Segment:
    day: int
    start_turn: int
    end_turn: int
    summary: str
    tags: dict = field(default_factory=dict)
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "summary": self.summary,
            "tags": self.tags,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Segment":
        return cls(
            day=int(data["day"]),
            start_turn=int(data.get("start_turn", 0)),
            end_turn=int(data.get("end_turn", 0)),
            summary=data.get("summary", ""),
            tags=data.get("tags") or {},
            embedding=data.get("embedding"),
        )


def _tokenize(text: str) -> list[str]:
    import jieba

    jieba.setLogLevel(60)
    return [t.strip() for t in jieba.lcut(text) if t.strip()]


def _minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _tag_boost(tags: dict, query: str) -> float:
    """人物 / 话题 / 地点 / 时间词命中时加分，最高 1.0。"""
    if not tags:
        return 0.0
    boost = 0.0
    for person in tags.get("people") or []:
        if person and str(person) in query:
            boost += 0.5
    for token in re.split(r"[/、,，\s]+", str(tags.get("topic") or "")):
        if token and token in query:
            boost += 0.3
    for token in re.split(r"[·/、,，\s]+", str(tags.get("place") or "")):
        if token and token in query:
            boost += 0.2
    time_tag = str(tags.get("time") or "")
    if time_tag:
        for word in ("去年", "前年", "上周", "上个月", "昨天", "今天", "十月"):
            if word in query and word in time_tag:
                boost += 0.3
                break
    return min(boost, 1.0)


class MemoryStore:
    """按用户隔离的记忆库；profile 是常驻画像，segments 是知识库片段。"""

    def __init__(self, profile: str = "", segments: list[Segment] | None = None):
        self.profile = profile
        self.segments: list[Segment] = list(segments or [])
        self._bm25 = None
        self._lock = threading.Lock()

    def add(self, segment: Segment) -> None:
        with self._lock:
            self.segments.append(segment)
            self._bm25 = None

    @property
    def max_day(self) -> int:
        return max((s.day for s in self.segments), default=1)

    def _ensure_bm25(self):
        if self._bm25 is not None:
            return self._bm25
        from rank_bm25 import BM25Okapi

        corpus = [_tokenize(s.summary) for s in self.segments]
        self._bm25 = BM25Okapi(corpus) if corpus else None
        return self._bm25

    def search(self, query: str, top_k: int = SEGMENT_RETRIEVE_TOP_K) -> list[str]:
        """返回按相关度排序、且做过去重的片段摘要。"""
        if not query.strip() or not self.segments:
            return []

        bm25_scores = [0.0] * len(self.segments)
        bm25 = self._ensure_bm25()
        if bm25 is not None:
            tokens = _tokenize(query)
            if tokens:
                bm25_scores = [float(x) for x in bm25.get_scores(tokens)]

        vec_scores = [0.0] * len(self.segments)
        try:
            from .embeddings import embed_texts

            query_vec = embed_texts([query])
            if query_vec and self.segments[0].embedding:
                q = query_vec[0]
                for i, seg in enumerate(self.segments):
                    if not seg.embedding:
                        continue
                    vec_scores[i] = sum(a * b for a, b in zip(q, seg.embedding))
        except Exception as exc:
            print(f"向量检索失败，退化为 BM25: {exc}")

        has_vector = any(v != 0.0 for v in vec_scores)
        if has_vector:
            vec_norm = _minmax(vec_scores)
            bm25_norm = _minmax(bm25_scores)
        else:
            vec_norm = [0.0] * len(self.segments)
            bm25_norm = _minmax(bm25_scores)

        is_update_query = any(word in query for word in RECENT_WORDS)
        recency_weight = UPDATE_RECENCY_WEIGHT if is_update_query else RECENCY_WEIGHT
        max_day = max(self.max_day, 1)

        fused: list[float] = []
        for i, seg in enumerate(self.segments):
            base = VECTOR_WEIGHT * vec_norm[i] + BM25_WEIGHT * bm25_norm[i]
            recency = recency_weight * (seg.day / max_day)
            tags = TAG_WEIGHT * _tag_boost(seg.tags, query)
            fused.append(base + recency + tags)

        ranked = sorted(range(len(self.segments)), key=lambda i: fused[i], reverse=True)

        # 同义片段去重：词面重合高、或向量几乎一样，都只留排名更靠前的一条
        token_sets = [set(_tokenize(s.summary)) for s in self.segments]
        selected: list[int] = []
        for i in ranked:
            duplicate = False
            for j in selected:
                if _jaccard(token_sets[i], token_sets[j]) >= DEDUP_THRESHOLD:
                    duplicate = True
                    break
                if _cosine(self.segments[i].embedding, self.segments[j].embedding) >= 0.85:
                    duplicate = True
                    break
            if duplicate:
                continue
            selected.append(i)
            if len(selected) == top_k:
                break

        return [self.segments[i].summary for i in selected]

    def to_dict(self) -> dict:
        return {"profile": self.profile, "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryStore":
        return cls(
            profile=data.get("profile", ""),
            segments=[Segment.from_dict(item) for item in data.get("segments", [])],
        )
