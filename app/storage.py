"""会话存储：单会话 + 片段化长期记忆。

生产路径（persist=True）：
- 每个用户只有一条连续对话，不再有 sessions 表；
- 距 last_active_at 超过 30 分钟，上一段自动收尾：压成 ≤200 字片段、写向量、更新画像；
- 历史消息按 id 游标分页，片段就是分页与检索的共同单位。

评测路径（persist=False）：
- 消息只在内存里流转，支持 summary / rag 两种模式，不写库、不碰 Redis。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, func

from .cache import get_memory, get_recent, invalidate_memory, set_memory, set_recent
from .db import SessionLocal, Message, Segment as SegmentRow, UserState
from .llm import summarize
from .memory import MemoryStore
from .memory.build import summarize_segment, update_profile
from .memory.embeddings import embed_texts
from .memory.store import Segment as MemorySegment
from .prompt import build_system_prompt
from .state import EmotionState, load_state

IDLE_MINUTES = 30
WINDOW = 6
SUMMARY_THRESHOLD = 20
SUMMARY_BATCH = 4


class Messages:
    def __init__(self, user_id: int, persist=True, mode="rag", memory=None):
        self.user_id = user_id
        self.persist = persist
        self.mode = mode
        self.memory = memory
        self.messages: list[dict] = []
        self.summary = ""
        self.summary_until_id = 0
        self.state = EmotionState()
        self.now = datetime.now()
        self.segment_id: int | None = None
        self._next_id = 1

    # ------------------------------------------------------------------ 入口
    def load_messages(self):
        self.messages = []
        if not self.persist:
            self.ensure_system()
            return

        self.segment_id = self._open_segment()
        recent = get_recent(self.user_id)
        if recent is None:
            recent = self._load_recent_db()
            set_recent(self.user_id, recent)
        self.messages = recent
        self.ensure_system()

    def ensure_system(self, query: str | None = None):
        """每轮重新渲染 system：人设 + 记忆槽 + 当前状态。"""
        state = self.state if not self.persist else load_state(self.user_id)

        if self.persist or self.mode == "rag":
            if not self.persist:
                self.memory = self.memory or MemoryStore()
            elif self.memory is None or query is not None:
                self.memory = self._load_memory()
            content = build_system_prompt(
                profile=self.memory.profile,
                segments=self.memory.search(query or ""),
                emotion=state.render_emotion(),
                relationship=state.render_relationship(),
                now=self.now,
            )
        else:
            content = build_system_prompt(
                summary=self.summary or None,
                emotion=state.render_emotion(),
                relationship=state.render_relationship(),
                now=self.now,
            )

        if not self.messages or self.messages[0]["role"] != "system":
            self.messages.insert(0, {"id": None, "role": "system", "content": content})
        else:
            self.messages[0]["content"] = content

    def save_messages(self):
        if not self.persist:
            for msg in self.messages:
                if msg["role"] == "system":
                    continue
                if msg["id"] is None:
                    msg["id"] = self._next_id
                    self._next_id += 1
            return

        with SessionLocal() as db:
            seg = db.get(SegmentRow, self.segment_id) if self.segment_id else None
            for msg in self.messages:
                if msg["role"] == "system" or msg["id"] is not None:
                    continue
                row = Message(
                    user_id=self.user_id,
                    segment_id=self.segment_id,
                    role=msg["role"],
                    content=msg["content"],
                )
                db.add(row)
                db.flush()
                msg["id"] = row.id
                if seg is not None:
                    seg.turn_count = (seg.turn_count or 0) + 1
            if seg is not None:
                seg.last_active_at = datetime.now()
            db.commit()

        recent = [
            {"id": m["id"], "role": m["role"], "content": m["content"]}
            for m in self.messages if m["role"] != "system"
        ][-WINDOW:]
        set_recent(self.user_id, recent)

    # ------------------------------------------------------------ 片段生命周期
    def _open_segment(self) -> int:
        with SessionLocal() as db:
            seg = db.execute(
                select(SegmentRow)
                .where(SegmentRow.user_id == self.user_id, SegmentRow.status == "open")
                .order_by(SegmentRow.seq.desc())
            ).scalars().first()
            if seg is not None:
                idle_minutes = (self.now - (seg.last_active_at or self.now)).total_seconds() / 60
                if idle_minutes <= IDLE_MINUTES or (seg.turn_count or 0) == 0:
                    return seg.id
                idle_segment_id = seg.id
            else:
                idle_segment_id = None

        if idle_segment_id is not None:
            self.close_segment(idle_segment_id)
        return self._create_segment()

    def _create_segment(self) -> int:
        with SessionLocal() as db:
            last_seq = db.execute(
                select(func.max(SegmentRow.seq)).where(SegmentRow.user_id == self.user_id)
            ).scalar() or 0
            seg = SegmentRow(
                user_id=self.user_id,
                seq=last_seq + 1,
                status="open",
                started_at=self.now,
                last_active_at=self.now,
                turn_count=0,
            )
            db.add(seg)
            db.commit()
            db.refresh(seg)
            return seg.id

    def close_segment(self, segment_id: int, api_key=None) -> None:
        """把一段对话压成 200 字记忆，写向量、更新画像，然后标记为 closed。"""
        with SessionLocal() as db:
            seg = db.get(SegmentRow, segment_id)
            if seg is None or seg.status != "open":
                return
            user_id = seg.user_id
            rows = db.execute(
                select(Message).where(Message.segment_id == segment_id).order_by(Message.id)
            ).scalars().all()
            turns = [{"role": row.role, "content": row.content} for row in rows]

        if not turns:
            with SessionLocal() as db:
                seg = db.get(SegmentRow, segment_id)
                if seg:
                    seg.status = "closed"
                    seg.ended_at = datetime.now()
                    db.commit()
            return

        summary = summarize_segment(turns, api_key=api_key)
        vectors = embed_texts([summary]) if summary else None

        with SessionLocal() as db:
            st = db.get(UserState, user_id)
            old_profile = (st.profile or "") if st else ""
        profile = update_profile(old_profile, summary, api_key=api_key) if summary else old_profile

        with SessionLocal() as db:
            seg = db.get(SegmentRow, segment_id)
            if seg is None:
                return
            seg.summary = summary
            seg.embedding = json.dumps(vectors[0]) if vectors else None
            seg.status = "closed"
            seg.ended_at = datetime.now()

            st = db.get(UserState, user_id)
            if st is None:
                st = UserState(user_id=user_id, profile=profile)
                db.add(st)
            else:
                st.profile = profile
            db.commit()

        invalidate_memory(user_id)

    # ------------------------------------------------------------------ 查询
    def _load_recent_db(self) -> list[dict]:
        if self.segment_id is None:
            return []
        with SessionLocal() as db:
            rows = db.execute(
                select(Message)
                .where(Message.user_id == self.user_id, Message.segment_id == self.segment_id)
                .order_by(Message.id.desc())
                .limit(WINDOW)
            ).scalars().all()
        return [{"id": r.id, "role": r.role, "content": r.content} for r in reversed(rows)]

    def _load_memory(self) -> MemoryStore:
        cached = get_memory(self.user_id)
        if cached:
            return MemoryStore.from_dict(cached)

        with SessionLocal() as db:
            state = db.get(UserState, self.user_id)
            profile = (state.profile or "") if state else ""
            rows = db.execute(
                select(SegmentRow)
                .where(SegmentRow.user_id == self.user_id, SegmentRow.status == "closed")
                .order_by(SegmentRow.seq)
            ).scalars().all()

        segments = []
        for row in rows:
            if not row.summary:
                continue
            try:
                embedding = json.loads(row.embedding) if row.embedding else None
            except (TypeError, ValueError):
                embedding = None
            segments.append(MemorySegment(
                day=row.seq,
                start_turn=row.started_at.timestamp() if row.started_at else 0,
                end_turn=row.ended_at.timestamp() if row.ended_at else 0,
                summary=row.summary,
                embedding=embedding,
            ))

        store = MemoryStore(profile=profile, segments=segments)
        set_memory(self.user_id, store.to_dict())
        return store

    def history(self, before_id: int | None = None, limit: int = 30) -> dict:
        with SessionLocal() as db:
            query = select(Message).where(Message.user_id == self.user_id)
            if before_id:
                query = query.where(Message.id < before_id)
            rows = db.execute(
                query.order_by(Message.id.desc()).limit(limit + 1)
            ).scalars().all()

        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "segment_id": row.segment_id,
            }
            for row in reversed(rows)
        ]
        return {
            "items": items,
            "has_more": has_more,
            "next_before_id": items[0]["id"] if items else None,
        }

    def warm_up(self) -> None:
        """登录后预热：当前段最近消息 + 画像/片段向量。"""
        if not self.persist:
            return
        with SessionLocal() as db:
            seg = db.execute(
                select(SegmentRow)
                .where(SegmentRow.user_id == self.user_id, SegmentRow.status == "open")
                .order_by(SegmentRow.seq.desc())
            ).scalars().first()
            self.segment_id = seg.id if seg else None
        if self.segment_id:
            set_recent(self.user_id, self._load_recent_db())
        self._load_memory()

    # ------------------------------------------------------------------ 上下文
    def get_context(self) -> list[dict]:
        """发给模型的消息：system（含记忆与状态）+ 最近 6 条。"""
        if not self.messages:
            return []
        if self.messages[0]["role"] != "system":
            return self.messages[-WINDOW:]

        real = self.messages[1:]
        if not self.persist and self.mode != "rag":
            if len(real) < SUMMARY_THRESHOLD:
                return self.messages
            if not self.summary:
                return [self.messages[0]] + real[-20:]

        return [self.messages[0]] + real[-WINDOW:]

    def maybe_summarize(self, api_key=None) -> None:
        """仅评测的摘要模式使用（persist=False），内存里滚动压缩。"""
        if self.persist:
            return
        try:
            real = self.messages[1:] if self.messages and self.messages[0]["role"] == "system" else self.messages
            if len(real) < SUMMARY_THRESHOLD:
                return
            split_index = len(real) - WINDOW
            to_summarize = [
                m for m in real[:split_index]
                if m["id"] and m["id"] > (self.summary_until_id or 0)
            ]
            if len(to_summarize) < SUMMARY_BATCH:
                return
            dialogue = "\n".join(f'{m["role"]}: {m["content"]}' for m in to_summarize)
            new_summary = summarize(self.summary, dialogue, api_key=api_key)
            if new_summary:
                self.summary = new_summary
                self.summary_until_id = to_summarize[-1]["id"]
        except Exception as exc:
            print(f"摘要压缩失败: {exc}")

    def get_system(self) -> str:
        return self.messages[0]["content"] if self.messages else ""
