"""会话片段（一天的对话）的存储与混合检索。

检索 = BM25（jieba 分词）+ 向量（bge-small-zh）min-max 融合，再加一点时间偏好。
13 段以内直接用内存索引，不引入 Chroma 这类外部服务，逻辑和线上一致。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..config import SEGMENT_RETRIEVE_TOP_K

VECTOR_WEIGHT = 0.7
BM25_WEIGHT = 0.3
RECENCY_WEIGHT = 0.08


@dataclass
class Segment:
    day: int
    start_turn: int
    end_turn: int
    summary: str
    embedding: list[float] | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "summary": self.summary,
            "embedding": self.embedding,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Segment":
        return cls(
            day=int(data["day"]),
            start_turn=int(data.get("start_turn", 0)),
            end_turn=int(data.get("end_turn", 0)),
            summary=data.get("summary", ""),
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
        """返回按相关度排序的片段摘要；向量不可用时自动退化为 BM25。"""
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
            fused = [
                VECTOR_WEIGHT * vec_norm[i] + BM25_WEIGHT * bm25_norm[i]
                for i in range(len(self.segments))
            ]
        else:
            fused = _minmax(bm25_scores)

        max_day = max(self.max_day, 1)
        ranked = sorted(
            range(len(self.segments)),
            key=lambda i: fused[i] + RECENCY_WEIGHT * (self.segments[i].day / max_day),
            reverse=True,
        )
        return [self.segments[i].summary for i in ranked[:top_k]]

    def to_dict(self) -> dict:
        return {"profile": self.profile, "segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryStore":
        return cls(
            profile=data.get("profile", ""),
            segments=[Segment.from_dict(item) for item in data.get("segments", [])],
        )
