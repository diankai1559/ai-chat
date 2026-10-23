-- 长期记忆的数据结构（设计稿，落地时翻译成 app/db.py 里的 SQLAlchemy 模型）
-- 检索单元是 segment（一次 30 分钟以内不中断的会话），不是单条消息。

-- ---------------------------------------------------------------
-- 会话片段：RAG 检索的基本单元
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),

    seq             INTEGER NOT NULL,                -- 该用户内的第几段，从 1 递增
    status          TEXT    NOT NULL DEFAULT 'open', -- open | closed

    started_at      DATETIME NOT NULL,
    last_active_at  DATETIME NOT NULL,               -- 最后一条消息时间，用来判 30 分钟空闲
    ended_at        DATETIME,                        -- closed 时写入
    turn_count      INTEGER NOT NULL DEFAULT 0,

    -- 关闭时由一次 LLM 调用同时产出，避免多次调用带来不一致
    summary         TEXT    DEFAULT '',
    tags_json       TEXT    DEFAULT '{}',            -- 时间/地点/人物/主题/时段
    emotion_json    TEXT    DEFAULT '{}',            -- 主情绪、强度、是否冲突
    open_loops_json TEXT    DEFAULT '[]',            -- 未完成事项，召回时提权
    importance      REAL    DEFAULT 0.5,             -- 0~1，注入排序用
    embedding       BLOB,                            -- 摘要向量；可为空，空则退化为 BM25

    created_at      DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_segments_user_seq      ON segments(user_id, seq);
CREATE INDEX IF NOT EXISTS ix_segments_user_status   ON segments(user_id, status);
CREATE INDEX IF NOT EXISTS ix_segments_user_ended_at ON segments(user_id, ended_at);

-- ---------------------------------------------------------------
-- 消息归属：给现有 messages 表加一列，删掉多会话依赖
-- ---------------------------------------------------------------
ALTER TABLE messages ADD COLUMN segment_id INTEGER REFERENCES segments(id);
CREATE INDEX IF NOT EXISTS ix_messages_segment_id_id ON messages(segment_id, id);
CREATE INDEX IF NOT EXISTS ix_messages_user_id_id    ON messages(user_id, id);

-- ---------------------------------------------------------------
-- 长期状态：情绪短周期、关系长周期，分开存，分开衰减
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_state (
    user_id            INTEGER PRIMARY KEY REFERENCES users(id),

    -- 情绪：分钟~小时级，按 exp(-Δt/τ) 向基线回归
    emotion_label      TEXT    DEFAULT '平静',
    emotion_intensity  REAL    DEFAULT 0.3,
    emotion_updated_at DATETIME,

    -- 关系：周~月级，缓慢累积，不做小时级衰减
    closeness          REAL    DEFAULT 0.5,   -- 亲密 0~1
    trust              REAL    DEFAULT 0.5,   -- 信任 0~1
    last_conflict_at   DATETIME,
    updated_at         DATETIME
);

-- ---------------------------------------------------------------
-- 可选：标签/关键词的全文检索。SQLite 自带 FTS5，不引入新依赖。
-- 内容列用空格分隔的词，供 BM25 粗排；向量为空时这是唯一召回通道。
-- ---------------------------------------------------------------
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    summary,
    keywords,
    content=''          -- contentless，由应用层同步写入
);
