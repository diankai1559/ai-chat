"""用例编排：一次对话怎么加载、怎么切段、怎么收尾。

四处分工（改代码前先看这四行）：
- app/domain/rules.py                 业务规则：多久算一段结束、模型看最近几条
- app/infrastructure/repositories.py  数据访问：所有 SQL 与 JSON 编解码
- app/application/prompt.py           提示词模板与记忆槽装配
- 本文件                              编排：把缓存、检索、提示词、模型调用按顺序串起来

生产路径（persist=True）：
- 每个用户只有一条连续对话，没有 sessions 表；
- 距 last_active_at 超过 30 分钟，上一段自动收尾：压成 ≤200 字片段、写向量、更新画像；
- 历史消息按 id 游标分页，片段就是分页与检索的共同单位。

评测路径（persist=False）：
- 消息只在内存里流转，支持 summary / rag 两种模式，不写库、不碰 Redis。
"""

from __future__ import annotations

from datetime import datetime

from ..domain.rules import RECENT_WINDOW, SUMMARY_BATCH, SUMMARY_THRESHOLD, segment_expired
from ..infrastructure import repositories as repo
from ..infrastructure.cache import get_memory, get_recent, invalidate_memory, set_memory, set_recent
from ..infrastructure.llm import summarize
from ..infrastructure.memory import MemoryStore
from ..infrastructure.memory.build import summarize_segment_tagged, update_profile
from ..infrastructure.memory.embeddings import embed_texts
from ..infrastructure.memory.store import Segment as MemorySegment
from .prompt import build_system_prompt
from .state import EmotionState, advance, load_state, save_state


class Messages:
    """一次对话的编排器：加载片段、装配上下文、保存本轮消息。

    生产（persist=True）走 SQLite + Redis；评测（persist=False）只在内存里跑。
    两套路径共用这个类，是为了让「评测用的」和「上线的」永远是同一份逻辑。
    """

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
        """加载当前片段最近几条消息；Redis 命中就直接用，没有再查库并回填。"""
        self.messages = []
        if not self.persist:
            self.ensure_system()
            return

        self.segment_id = self._open_segment()

        recent = get_recent(self.user_id)
        if recent is None:
            recent = repo.recent_messages(self.user_id, self.segment_id, RECENT_WINDOW)
            set_recent(self.user_id, recent)

        self.messages = recent
        self.ensure_system()

    def ensure_system(self, query: str | None = None):
        """每轮重新渲染 system：人设 + 记忆槽 + 当前状态。

        query 是用户这一轮说的话，用来现场检索相关往事；
        摘要模式（评测的对照组）走另一条分支，只注入一份摘要。
        """
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
        """保存本轮新增消息，并刷新 Redis 里的最近几条（评测模式下只补内存 id）。"""
        if not self.persist:
            for msg in self.messages:
                if msg["role"] == "system":
                    continue
                if msg["id"] is None:
                    msg["id"] = self._next_id
                    self._next_id += 1
            return

        pending = [
            m for m in self.messages
            if m["role"] != "system" and m["id"] is None
        ]
        new_ids = repo.append_messages(self.user_id, self.segment_id, pending)
        for msg, msg_id in zip(pending, new_ids):
            msg["id"] = msg_id

        recent = [
            {"id": m["id"], "role": m["role"], "content": m["content"]}
            for m in self.messages if m["role"] != "system"
        ][-RECENT_WINDOW:]
        set_recent(self.user_id, recent)

    # ------------------------------------------------------------ 片段生命周期

    def _open_segment(self) -> int:
        """取当前片段；空闲超时且这一段聊过，就先收尾旧段再开新段。"""
        segment = repo.find_open_segment(self.user_id)
        if segment is None:
            return repo.create_segment(self.user_id, self.now)

        if not segment_expired(segment["last_active_at"], segment["turn_count"], self.now):
            return segment["id"]

        self.close_segment(segment["id"])
        return repo.create_segment(self.user_id, self.now)

    def close_segment(self, segment_id: int, api_key=None) -> None:
        """把一段对话压成 200 字记忆：写摘要与标签、算向量、更新画像，最后标记 closed。"""
        segment = repo.get_segment(segment_id)
        if segment is None or segment["status"] != "open":
            return

        user_id = segment["user_id"]
        turns = repo.segment_turns(segment_id)

        # 空片段不用调模型，直接关掉
        if not turns:
            repo.mark_segment_closed(segment_id, datetime.now())
            return

        summary, tags = summarize_segment_tagged(turns, api_key=api_key)
        vectors = embed_texts([summary]) if summary else None

        old_profile = repo.load_profile(user_id)
        profile = update_profile(old_profile, summary, api_key=api_key) if summary else old_profile

        repo.save_closed_segment(
            segment_id,
            summary=summary,
            tags=tags,
            embedding=vectors[0] if vectors else None,
            ended_at=datetime.now(),
            profile=profile,
        )

        # 画像和片段都变了，旧缓存作废，下一轮重新装配
        invalidate_memory(user_id)

    # ------------------------------------------------------------------ 查询

    def _load_memory(self) -> MemoryStore:
        """读常驻画像 + 已关闭片段；Redis 命中直接复用，未命中查库后回填。"""
        cached = get_memory(self.user_id)
        if cached:
            return MemoryStore.from_dict(cached)

        segments = [
            MemorySegment(
                day=row["seq"],
                start_turn=row["started_at"].timestamp() if row["started_at"] else 0,
                end_turn=row["ended_at"].timestamp() if row["ended_at"] else 0,
                summary=row["summary"],
                tags=row["tags"],
                embedding=row["embedding"],
            )
            for row in repo.closed_segments(self.user_id)
            if row["summary"]          # 没压出摘要的片段不参与召回
        ]

        store = MemoryStore(profile=repo.load_profile(self.user_id), segments=segments)
        set_memory(self.user_id, store.to_dict())
        return store

    def history(self, before_id: int | None = None, limit: int = 30) -> dict:
        """按 id 游标分页拉历史；不传 before_id 就是最新一页。"""
        return repo.page_messages(self.user_id, before_id, limit)

    def warm_up(self) -> None:
        """登录预热：当前片段最近消息 + 画像/片段向量提前进 Redis。"""
        if not self.persist:
            return

        segment = repo.find_open_segment(self.user_id)
        self.segment_id = segment["id"] if segment else None

        if self.segment_id:
            set_recent(
                self.user_id,
                repo.recent_messages(self.user_id, self.segment_id, RECENT_WINDOW),
            )
        self._load_memory()

    # ------------------------------------------------------------------ 上下文

    def get_context(self) -> list[dict]:
        """发给模型的消息：system（含记忆与状态）+ 最近 6 条。"""
        if not self.messages:
            return []
        if self.messages[0]["role"] != "system":
            return self.messages[-RECENT_WINDOW:]

        real = self.messages[1:]
        # 评测的摘要模式：攒不够就从最近的开始发，攒够了才用摘要换掉中段
        if not self.persist and self.mode != "rag":
            if len(real) < SUMMARY_THRESHOLD:
                return self.messages
            if not self.summary:
                return [self.messages[0]] + real[-20:]

        return [self.messages[0]] + real[-RECENT_WINDOW:]

    def maybe_summarize(self, api_key=None) -> None:
        """仅评测的摘要模式使用（persist=False），在内存里滚动压缩。"""
        if self.persist:
            return

        try:
            real = self.messages[1:] if self.messages and self.messages[0]["role"] == "system" else self.messages
            if len(real) < SUMMARY_THRESHOLD:
                return

            split_index = len(real) - RECENT_WINDOW
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
        """取当前 system 文本，供调试和评测记录实际发给模型的内容。"""
        return self.messages[0]["content"] if self.messages else ""


# ------------------------------------------------------------------ 后台任务

def warm_up(user_id: int) -> None:
    """登录后预热：最近消息与记忆向量写进 Redis，降低首轮延迟。

    任何异常都只打印，绝不让预热失败影响登录本身。
    """
    try:
        Messages(user_id=user_id).warm_up()
    except Exception as e:
        print(f"预热失败: {e}")


def update_state_after_reply(user_id: int, user_message: str, reply: str, api_key=None) -> None:
    """回复结束后推进情绪 / 关系状态；由路由放进后台线程，不阻塞本轮响应。"""
    try:
        previous = load_state(user_id)
        save_state(user_id, advance(previous, user_message, reply, api_key=api_key))
    except Exception as e:
        print(f"后台状态更新失败: {e}")
