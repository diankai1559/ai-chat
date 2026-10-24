"""数据模型：用户、片段、消息、状态。

单会话后不再有 sessions 表；一条消息属于某个片段（segment），
片段既是历史分页的锚点，也是长期记忆的检索单元。
"""

from datetime import datetime

from sqlalchemy import create_engine, ForeignKey
from sqlalchemy import Column, Integer, String, Text, DateTime, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

from .config import DB_PATH, DATA_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH.as_posix()}")
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Segment(Base):
    """一次连续会话（30 分钟无消息即结束），也是知识库的一个片段。"""
    __tablename__ = "segments"
    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)                 # 用户内第几段
    status = Column(String(10), nullable=False, default="open")  # open | closed
    started_at = Column(DateTime, default=datetime.now, nullable=False)
    last_active_at = Column(DateTime, default=datetime.now, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    turn_count = Column(Integer, default=0, nullable=False)
    summary = Column(Text, default="", nullable=False)
    tags_json = Column(Text, default="{}", nullable=False)  # 时间/地点/人物/情绪/话题/未完成事项
    embedding = Column(Text, nullable=True)               # JSON 数组
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    segment_id = Column(ForeignKey("segments.id"), nullable=True)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class UserState(Base):
    """情绪（短周期）、关系（长周期）与常驻画像。"""
    __tablename__ = "user_states"
    user_id = Column(ForeignKey("users.id"), primary_key=True)
    emotion = Column(String(20), default="平静", nullable=False)
    intensity = Column(Float, default=0.2, nullable=False)
    closeness = Column(Float, default=0.4, nullable=False)
    profile = Column(Text, default="", nullable=False)
    updated_at = Column(DateTime, default=datetime.now, nullable=False)


Base.metadata.create_all(engine)
