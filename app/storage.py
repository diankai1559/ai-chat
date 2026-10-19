from sqlalchemy import select, delete
from .cache import get_messages,set_messages
from .llm import summarize
from .db import SessionLocal, Session, Message, User


class Messages:
    def __init__(self, user_id: int, session_uuid=None, name="新会话"):
        self.session_uuid = session_uuid  # 唯一标识
        self.user_id = user_id
        self.name = name                   # 显示名
        self.messages = []
        self.id = None                     # DB 中的 Integer 主键

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

    def ensure_system(self):
        if not self.messages or self.messages[0]["role"] != "system":
            self.messages.insert(0, {
                "id": None,
                "role": "system",
                "content": "你是一个简洁的助手，回答不超过 50 字。"
            })

    def save_messages(self):
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
        """返回发给模型的消息列表（只读，绝不触发压缩，保证首字不被阻塞）。"""
        RETAIN = 6
        THRESHOLD = 20
        real_messages = self.messages[1:] if self.messages[0]["role"] == "system" else self.messages

        if len(real_messages) < THRESHOLD:
            return self.messages

        old_summary = None
        with SessionLocal() as db:
            result = db.execute(
                select(Session).where(Session.uuid == self.session_uuid)
            ).scalars().one_or_none()
            if result:
                old_summary = result.summary

        new_messages = [self.messages[0]]
        if old_summary:
            split_index = len(real_messages) - RETAIN
            new_messages.append({"id": None, "role": "system", "content": "【早前对话摘要】" + old_summary})
            new_messages += real_messages[split_index:]
        else:
            # 尚未压缩：先返回全部避免丢信息，压缩交给回复后的 maybe_summarize 后台执行
            new_messages += real_messages
        return new_messages

    def maybe_summarize(self):
        """回复完成后调用（可在后台线程执行）：上下文超限则无感压缩历史。"""
        RETAIN = 6
        THRESHOLD = 20
        BATCH = 10
        try:
            real_messages = self.messages[1:] if self.messages[0]["role"] == "system" else self.messages
            if len(real_messages) < THRESHOLD:
                return
            split_index = len(real_messages) - RETAIN
            with SessionLocal() as db:
                result = db.execute(
                    select(Session).where(Session.uuid == self.session_uuid)
                ).scalars().one_or_none()
                if not result:
                    return
                last_summarized_id = result.summary_until_id
                old_summary = result.summary
                to_summarize = [m for m in real_messages[:split_index] if m["id"] and m["id"] > (last_summarized_id or 0)]
                if len(to_summarize) < BATCH:
                    return
                dialogue_text = "\n".join(f'{m["role"]}: {m["content"]}' for m in to_summarize)
                new_summary = summarize(old_summary, dialogue_text)
                if new_summary:
                    result.summary = new_summary
                    result.summary_until_id = to_summarize[-1]["id"]
                    db.commit()
        except Exception as e:
            print(f"后台摘要压缩失败: {e}")


