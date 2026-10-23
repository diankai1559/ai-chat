from datetime import datetime

from sqlalchemy import select, delete
from .cache import get_messages,set_messages
from .llm import summarize
from .prompt import build_system_prompt
from .state import EmotionState, load_state
from .db import SessionLocal, Session, Message, User


class Messages:
    def __init__(self, user_id: int, session_uuid=None, name="新会话",
                 persist=True, mode="summary", memory=None):
        self.session_uuid = session_uuid  # 唯一标识
        self.user_id = user_id
        self.name = name                   # 显示名
        self.messages = []
        self.id = None                     # DB 中的 Integer 主键
        self.summary = ""                  # 最近一次渲染用的摘要，供 get_context 判断
        self.summary_until_id = 0
        # persist=False：只在内存里跑，不建会话、不写库、不碰 Redis，供评测脚本使用
        self.persist = persist
        self.state = EmotionState()
        self._next_id = 1
        # mode="summary" 是摘要版；mode="rag" 走片段检索 + 常驻画像
        self.mode = mode
        self.memory = memory
        self.now = datetime.now()          # 允许评测时用虚拟时间模拟“隔天”

    def get_or_create_session(self):
        """确保会话存在，返回其数据库主键 id。"""
        with SessionLocal() as db:
            s = None
            if self.session_uuid:
                s = db.execute(
                    select(Session).where(
                        Session.uuid == self.session_uuid,
                        Session.user_id == self.user_id,
                    )
                ).scalars().one_or_none()

            if s is None:
                # 创建新会话
                s = Session(user_id=self.user_id)
                db.add(s)
                db.commit()
                db.refresh(s)

            self.id = s.id
            self.session_uuid = s.uuid
            self.name = s.name
            return s.id

    def load_messages(self):
        self.messages = []
        if not self.persist:
            self.ensure_system()
            return
        session_id = self.get_or_create_session()
        result = get_messages(self.session_uuid)
        if result is not None:
            self.messages = result
        else:
            try:
                with SessionLocal() as db:
                    result = db.execute(
                        select(Message).where(Message.session_id == session_id)
                    )
                    for i in result.scalars().all():
                        if i.role == "system":
                            continue
                        self.messages.append({"id": i.id, "role": i.role, "content": i.content})
                set_messages(self.session_uuid, self.messages)
            except Exception as e:
                print(e)
        self.ensure_system()

    def ensure_system(self, query: str | None = None):
        """每轮重新渲染 system：人设 + 记忆槽 + 当前情绪状态。

        摘要模式用滚动摘要；RAG 模式用常驻画像 + 按 query 现场检索的片段。
        情绪每轮都会变，不能只在首次加载时写一次。
        """
        summary = ""
        if not self.persist:
            summary = (self.summary or "").strip()
        elif self.session_uuid:
            with SessionLocal() as db:
                s = db.execute(
                    select(Session).where(Session.uuid == self.session_uuid)
                ).scalars().one_or_none()
                if s:
                    summary = (s.summary or "").strip()

        self.summary = summary
        state = self.state if not self.persist else load_state(self.user_id)

        if self.mode == "rag" and self.memory is not None:
            content = build_system_prompt(
                profile=self.memory.profile,
                segments=self.memory.search(query or ""),
                emotion=state.render_emotion(),
                relationship=state.render_relationship(),
                now=self.now,
            )
        else:
            content = build_system_prompt(
                summary=summary or None,
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
            # 只在内存里编 id，压缩逻辑靠 id 判断进度，不落库
            for msg in self.messages:
                if msg["role"] == "system":
                    continue
                if msg["id"] is None:
                    msg["id"] = self._next_id
                    self._next_id += 1
            return

        if self.id is None:
            session_id = self.get_or_create_session()
        else:
            session_id = self.id

        with SessionLocal() as db:
            session = db.execute(
                select(Session).where(Session.id == session_id)
            ).scalars().one_or_none()

            if session is None:
                # session 被删了，重新创建
                session = Session(name=self.name, user_id=self.user_id)
                db.add(session)
                db.commit()
                db.refresh(session)
                self.id = session.id
                self.session_uuid = session.uuid
                session_id = session.id

            for i in self.messages:
                if i["id"] is None:
                    if i["role"] == "system":
                        continue
                    msg = Message(session_id=session_id, role=i["role"], content=i["content"])
                    db.add(msg)
                    db.flush()
                    i["id"] = msg.id
            db.commit()
            real = [i for i in self.messages if i["role"] != "system"]
            set_messages(self.session_uuid, real)

    # def clear(self):
    #     self.messages = self.messages[:1]
    #     self.save_messages()

    def set_system(self, content):
        self.ensure_system()
        self.messages[0]["content"] = content
        self.save_messages()

    def get_system(self):
        return self.messages[0]["content"]

    def switch(self, session_uuid):
        self.save_messages()
        self.session_uuid = session_uuid
        self.get_or_create_session()
        self.load_messages()

    def rename(self, new_name):
        """更新会话显示名"""
        if self.id is None:
            self.get_or_create_session()
        with SessionLocal() as db:
            session = db.execute(
                select(Session).where(Session.id == self.id, Session.user_id == self.user_id)
            ).scalars().one_or_none()
            if session:
                session.name = new_name
                db.commit()
                self.name = new_name

    def get_context(self):
        """返回发给模型的消息列表（只读，绝不触发压缩，保证首字不被阻塞）。

        早前对话已由 system 提示词里的「较早的对话」槽位承载，
        这里只保留最近的几轮，避免同一份摘要被注入两次。
        """
        RETAIN = 6
        FALLBACK = 20
        THRESHOLD = 20
        real_messages = self.messages[1:] if self.messages[0]["role"] == "system" else self.messages

        if len(real_messages) < THRESHOLD:
            return self.messages

        # RAG 模式的早前内容在片段库里，窗口和摘要版一样只留最近 6 条
        if self.mode == "rag":
            return [self.messages[0]] + real_messages[-RETAIN:]

        # 摘要尚未生成（后台还没跑完或调用失败）时退回最近 20 条，
        # 不能只发 6 条——否则中间这段信息两头都不在，等于整段失忆。
        if not self.summary:
            return [self.messages[0]] + real_messages[-FALLBACK:]

        return [self.messages[0]] + real_messages[-RETAIN:]

    def maybe_summarize(self, api_key=None):
        """回复完成后调用（可在后台线程执行）：上下文超限则无感压缩历史。"""
        RETAIN = 6
        THRESHOLD = 20
        BATCH = 4   # 每次只压缩 2 轮：太小浪费调用，太大就会留下「摘要与窗口之间」的失忆空档
        try:
            real_messages = self.messages[1:] if self.messages[0]["role"] == "system" else self.messages
            if len(real_messages) < THRESHOLD:
                return
            split_index = len(real_messages) - RETAIN

            if self.persist:
                with SessionLocal() as db:
                    result = db.execute(
                        select(Session).where(Session.uuid == self.session_uuid)
                    ).scalars().one_or_none()
                    if not result:
                        return
                    session_id = result.id
                    last_summarized_id = result.summary_until_id
                    old_summary = result.summary
            else:
                session_id = None
                last_summarized_id = self.summary_until_id
                old_summary = self.summary

            to_summarize = [
                m for m in real_messages[:split_index]
                if m["id"] and m["id"] > (last_summarized_id or 0)
            ]
            if len(to_summarize) < BATCH:
                return

            dialogue_text = "\n".join(f'{m["role"]}: {m["content"]}' for m in to_summarize)
            new_summary = summarize(old_summary, dialogue_text, api_key=api_key)
            if not new_summary:
                return

            until_id = to_summarize[-1]["id"]
            self.summary = new_summary
            self.summary_until_id = until_id

            if self.persist:
                with SessionLocal() as db:
                    row = db.execute(
                        select(Session).where(Session.id == session_id)
                    ).scalars().one_or_none()
                    if row:
                        row.summary = new_summary
                        row.summary_until_id = until_id
                        db.commit()
        except Exception as e:
            print(f"后台摘要压缩失败: {e}")


