"""一次性迁移：多会话 → 单会话 + 知识库片段。

- sessions 表里的每个会话迁成一个 closed 片段（保留原摘要）
- messages 增加 user_id / segment_id，去掉 session_id
- user_states 增加 profile 字段
- 迁移前自动备份数据库，可重复执行（sessions 不存在时直接跳过）

用法：python -m eval.migrate_sessions_to_segments
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from app.config import DB_PATH


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def column_exists(cur: sqlite3.Cursor, table: str, column: str) -> bool:
    return any(row[1] == column for row in cur.execute(f"PRAGMA table_info({table})"))


def main() -> None:
    if not DB_PATH.exists():
        print("数据库不存在，无需迁移")
        return

    backup = DB_PATH.with_name(f"chat.db.bak_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(DB_PATH, backup)
    print(f"已备份: {backup}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if not table_exists(cur, "sessions"):
        print("没有 sessions 表，已完成过迁移，跳过")
        return

    cur.execute("""
        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            status VARCHAR(10) NOT NULL DEFAULT 'open',
            started_at DATETIME NOT NULL,
            last_active_at DATETIME NOT NULL,
            ended_at DATETIME,
            turn_count INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            embedding TEXT,
            created_at DATETIME NOT NULL
        )
    """)

    sessions = cur.execute("""
        SELECT id, user_id, created_at, summary
        FROM sessions
        WHERE user_id IS NOT NULL
        ORDER BY user_id, created_at
    """).fetchall()

    session_to_segment: dict[int, int] = {}
    seq_by_user: dict[int, int] = {}

    for session in sessions:
        count = cur.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?", (session["id"],)
        ).fetchone()[0]
        if count == 0:
            continue

        last = cur.execute(
            "SELECT MAX(created_at) FROM messages WHERE session_id=?", (session["id"],)
        ).fetchone()[0] or session["created_at"]

        seq = seq_by_user.get(session["user_id"], 0) + 1
        seq_by_user[session["user_id"]] = seq

        cur.execute("""
            INSERT INTO segments
                (user_id, seq, status, started_at, last_active_at, ended_at,
                 turn_count, summary, embedding, created_at)
            VALUES (?, ?, 'closed', ?, ?, ?, ?, ?, NULL, ?)
        """, (
            session["user_id"], seq, session["created_at"], last, last,
            count, session["summary"] or "", session["created_at"],
        ))
        session_to_segment[session["id"]] = cur.lastrowid

    # 重建 messages 表
    cur.execute("ALTER TABLE messages RENAME TO messages_legacy")
    cur.execute("""
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            segment_id INTEGER,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME NOT NULL
        )
    """)

    user_of_session = {s["id"]: s["user_id"] for s in sessions}
    rows = cur.execute(
        "SELECT id, session_id, role, content, created_at FROM messages_legacy ORDER BY id"
    ).fetchall()
    for row in rows:
        user_id = user_of_session.get(row["session_id"])
        if user_id is None:
            continue
        cur.execute("""
            INSERT INTO messages (id, user_id, segment_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            row["id"], user_id, session_to_segment.get(row["session_id"]),
            row["role"], row["content"], row["created_at"],
        ))

    cur.execute("DROP TABLE messages_legacy")
    cur.execute("DROP TABLE sessions")

    if table_exists(cur, "user_states") and not column_exists(cur, "user_states", "profile"):
        cur.execute("ALTER TABLE user_states ADD COLUMN profile TEXT NOT NULL DEFAULT ''")

    cur.execute("CREATE INDEX IF NOT EXISTS ix_segments_user_seq ON segments(user_id, seq)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_segments_user_status ON segments(user_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_messages_user_id ON messages(user_id, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_messages_segment_id ON messages(segment_id, id)")

    conn.commit()

    print(f"迁移完成：{len(session_to_segment)} 个会话 → 片段，{len(rows)} 条消息")
    for user_id, seq in seq_by_user.items():
        print(f"  user {user_id}: {seq} 段")
    conn.close()


if __name__ == "__main__":
    main()
