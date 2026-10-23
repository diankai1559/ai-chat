import uuid
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


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = Column(ForeignKey("users.id"), nullable=True)
    name = Column(String(50), nullable=False, default="新会话")
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    summary = Column(Text, default="", nullable=False)
    summary_until_id = Column(Integer, default=0 , nullable=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    session_id = Column(ForeignKey("sessions.id"), nullable=False)
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
    """情绪（短周期）与关系（长周期）状态，按用户持久化。"""
    __tablename__ = "user_states"
    user_id = Column(ForeignKey("users.id"), primary_key=True)
    emotion = Column(String(20), default="平静", nullable=False)
    intensity = Column(Float, default=0.2, nullable=False)
    closeness = Column(Float, default=0.4, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, nullable=False)


Base.metadata.create_all(engine)