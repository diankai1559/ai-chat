"""数据访问层：用户、片段、消息、画像、情绪状态的所有 SQL。

只做「翻译」——把数据库行映射成普通 dict，把 dict 落成行；不做业务判断。
什么时候开新片段、要不要压缩、怎么装配提示词，都由 application/chat_service.py 决定。

JSON 的编解码也收在这一层：tags / embedding 在库里是 TEXT，
上层拿到的永远是 dict / list，不需要知道存储格式。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, func

from .db import SessionLocal, Message, Segment, User, UserState


def _decode(raw, default):
    """把库里存的 JSON 文本解析回对象；空值或脏数据都退回默认值。"""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ 片段

def find_open_segment(user_id: int) -> dict | None:
    """取该用户当前打开的片段（seq 最大的那个），没有返回 None。"""
    with SessionLocal() as db:
        row = db.execute(
            select(Segment)
            .where(Segment.user_id == user_id, Segment.status == "open")
            .order_by(Segment.seq.desc())
        ).scalars().first()
        if row is None:
            return None
        return {
            "id": row.id,
            "seq": row.seq,
            "last_active_at": row.last_active_at,
            "turn_count": row.turn_count or 0,
        }


def get_segment(segment_id: int) -> dict | None:
    """按 id 取片段状态，用来防止同一片段被重复收尾。"""
    with SessionLocal() as db:
        row = db.get(Segment, segment_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "user_id": row.user_id,
            "status": row.status,
        }


def create_segment(user_id: int, now: datetime) -> int:
    """新建一个 open 片段，seq 接着该用户上一段递增。"""
    with SessionLocal() as db:
        last_seq = db.execute(
            select(func.max(Segment.seq)).where(Segment.user_id == user_id)
        ).scalar() or 0

        row = Segment(
            user_id=user_id,
            seq=last_seq + 1,
            status="open",
            started_at=now,
            last_active_at=now,
            turn_count=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def save_closed_segment(
    segment_id: int,
    *,
    summary: str,
    tags: dict,
    embedding: list[float] | None,
    ended_at: datetime,
    profile: str,
) -> None:
    """同一事务里写入片段摘要/标签/向量并更新常驻画像，最后标记为 closed。

    放在一个事务里，是为了避免「片段关了但画像没更新」的半截状态。
    """
    with SessionLocal() as db:
        row = db.get(Segment, segment_id)
        if row is None:
            return

        row.summary = summary
        row.tags_json = json.dumps(tags, ensure_ascii=False)
        row.embedding = json.dumps(embedding) if embedding else None
        row.status = "closed"
        row.ended_at = ended_at

        state = db.get(UserState, row.user_id)
        if state is None:
            db.add(UserState(user_id=row.user_id, profile=profile))
        else:
            state.profile = profile

        db.commit()


def mark_segment_closed(segment_id: int, ended_at: datetime) -> None:
    """空片段直接关掉，不需要压缩，也不动画像。"""
    with SessionLocal() as db:
        row = db.get(Segment, segment_id)
        if row is None:
            return
        row.status = "closed"
        row.ended_at = ended_at
        db.commit()


def closed_segments(user_id: int) -> list[dict]:
    """该用户所有已关闭片段，按 seq 升序，摘要/标签/向量一并取出。

    是否参与召回由上层的 storage 判断（本文只负责取数据）。
    """
    with SessionLocal() as db:
        rows = db.execute(
            select(Segment)
            .where(Segment.user_id == user_id, Segment.status == "closed")
            .order_by(Segment.seq)
        ).scalars().all()

        return [
            {
                "seq": row.seq,
                "started_at": row.started_at,
                "ended_at": row.ended_at,
                "turn_count": row.turn_count or 0,
                "summary": row.summary or "",
                "tags": _decode(row.tags_json, {}),
                "embedding": _decode(row.embedding, None),
            }
            for row in rows
        ]


# ------------------------------------------------------------------ 消息

def append_messages(user_id: int, segment_id: int | None, messages: list[dict]) -> list[int]:
    """把一批新消息落库，同时累加片段轮数与最后活跃时间，返回对应的自增 id。"""
    if not messages:
        return []

    ids: list[int] = []
    with SessionLocal() as db:
        segment = db.get(Segment, segment_id) if segment_id else None
        for msg in messages:
            row = Message(
                user_id=user_id,
                segment_id=segment_id,
                role=msg["role"],
                content=msg["content"],
            )
            db.add(row)
            db.flush()
            ids.append(row.id)
            if segment is not None:
                segment.turn_count = (segment.turn_count or 0) + 1

        if segment is not None:
            segment.last_active_at = datetime.now()
        db.commit()

    return ids


def recent_messages(user_id: int, segment_id: int | None, limit: int) -> list[dict]:
    """当前片段最近 limit 条消息，按时间正序返回（旧 → 新）。"""
    if segment_id is None:
        return []

    with SessionLocal() as db:
        rows = db.execute(
            select(Message)
            .where(Message.user_id == user_id, Message.segment_id == segment_id)
            .order_by(Message.id.desc())
            .limit(limit)
        ).scalars().all()

        return [{"id": row.id, "role": row.role, "content": row.content} for row in reversed(rows)]


def segment_turns(segment_id: int) -> list[dict]:
    """片段内全部消息，按时间正序，用于压缩成记忆。"""
    with SessionLocal() as db:
        rows = db.execute(
            select(Message).where(Message.segment_id == segment_id).order_by(Message.id)
        ).scalars().all()

        return [{"role": row.role, "content": row.content} for row in rows]


def page_messages(user_id: int, before_id: int | None, limit: int) -> dict:
    """按 id 游标分页：多取一条判断是否还有更早的，再按时间正序返回这一页。"""
    with SessionLocal() as db:
        query = select(Message).where(Message.user_id == user_id)
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


# ------------------------------------------------------------------ 画像

def load_profile(user_id: int) -> str:
    """常驻画像；没有记录时返回空串。"""
    with SessionLocal() as db:
        row = db.get(UserState, user_id)
        return (row.profile or "") if row else ""


def load_emotion_state(user_id: int) -> dict | None:
    """情绪 / 关系状态；没有记录返回 None，由上层决定用默认值。"""
    with SessionLocal() as db:
        row = db.get(UserState, user_id)
        if row is None:
            return None
        return {
            "emotion": row.emotion,
            "intensity": row.intensity,
            "closeness": row.closeness,
            "updated_at": row.updated_at,
        }


def save_emotion_state(
    user_id: int,
    *,
    emotion: str,
    intensity: float,
    closeness: float,
    updated_at: datetime,
) -> None:
    """写回情绪 / 关系状态；行不存在就补一条。"""
    with SessionLocal() as db:
        row = db.get(UserState, user_id)
        if row is None:
            row = UserState(user_id=user_id)
            db.add(row)
        row.emotion = emotion
        row.intensity = intensity
        row.closeness = closeness
        row.updated_at = updated_at
        db.commit()


# ------------------------------------------------------------------ 用户

def find_user_by_name(username: str):
    """按用户名取用户行；注册要查重，登录要取密码哈希。"""
    with SessionLocal() as db:
        return db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()


def get_user(user_id: int):
    """按 id 取用户行；token 有效但用户已被删时返回 None。"""
    with SessionLocal() as db:
        return db.get(User, user_id)


def create_user(username: str, password_hash: str):
    """新建用户；用户名重复时由数据库唯一约束抛 IntegrityError，交给上层翻译成 400。"""
    with SessionLocal() as db:
        user = User(username=username, password_hash=password_hash)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
