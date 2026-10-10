from sqlalchemy import select, delete

from .db import SessionLocal, Session, Message


class Messages:
    def __init__(self, session_uuid=None, name="新会话"):
        self.session_uuid = session_uuid  # 唯一标识
        self.name = name                   # 显示名
        self.messages = []
        self.id = None                     # DB 中的 Integer 主键

    def _get_or_create_session(self):
        """确保会话存在，返回其数据库主键 id。"""
        with SessionLocal() as db:
            s = None
            if self.session_uuid:
                s = db.execute(
                    select(Session).where(Session.uuid == self.session_uuid)
                ).scalars().one_or_none()

            if s is None:
                # 创建新会话
                s = Session(name=self.name)
                db.add(s)
                db.commit()
                db.refresh(s)

            self.id = s.id
            self.session_uuid = s.uuid
            self.name = s.name
            return s.id

    def load_messages(self):
        self.messages = []
        session_id = self._get_or_create_session()
        try:
            with SessionLocal() as db:
                result = db.execute(
                    select(Message).where(Message.session_id == session_id)
                )
                for i in result.scalars().all():
                    self.messages.append({"role": i.role, "content": i.content})
        except Exception as e:
            print(e)
        self.ensure_system()

    def ensure_system(self):
        if not self.messages or self.messages[0]["role"] != "system":
            self.messages.insert(0, {
                "role": "system",
                "content": "你是一个简洁的助手，回答不超过 50 字。"
            })

    def save_messages(self):
        if self.id is None:
            session_id = self._get_or_create_session()
        else:
            session_id = self.id

        with SessionLocal() as db:
            session = db.execute(
                select(Session).where(Session.id == session_id)
            ).scalars().one_or_none()

            if session is None:
                # session 被删了，重新创建
                session = Session(name=self.name)
                db.add(session)
                db.commit()
                db.refresh(session)
                self.id = session.id
                self.session_uuid = session.uuid
                session_id = session.id

            db.execute(delete(Message).where(Message.session_id == session_id))
            for i in self.messages:
                db.add(Message(session_id=session_id, role=i["role"], content=i["content"]))
            db.commit()

    def clear(self):
        self.messages = self.messages[:1]
        self.save_messages()

    def set_system(self, content):
        self.ensure_system()
        self.messages[0]["content"] = content
        self.save_messages()

    def get_system(self):
        return self.messages[0]["content"]

    def switch(self, session_uuid):
        self.save_messages()
        self.session_uuid = session_uuid
        self._get_or_create_session()
        self.load_messages()

    def rename(self, new_name):
        """更新会话显示名"""
        if self.id is None:
            self._get_or_create_session()
        with SessionLocal() as db:
            session = db.execute(
                select(Session).where(Session.id == self.id)
            ).scalars().one_or_none()
            if session:
                session.name = new_name
                db.commit()
                self.name = new_name