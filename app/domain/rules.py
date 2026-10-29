"""业务规则：阈值常量 + 纯函数。

这里刻意不 import 数据库、Redis、requests、FastAPI，
所以「多久算一段对话结束」这类判断可以脱离运行环境单独验证，
也可以在面试时直接指出规则写在哪一行。
"""

from __future__ import annotations

from datetime import datetime

IDLE_MINUTES = 30        # 多久没说话，就把上一段对话收尾
RECENT_WINDOW = 6        # 每轮实际送给模型的最近消息条数
SUMMARY_THRESHOLD = 20   # 评测的摘要模式：攒够多少条才开始压缩
SUMMARY_BATCH = 4        # 一次至少压缩几条，避免频繁调模型


def segment_expired(last_active_at: datetime | None, turn_count: int, now: datetime) -> bool:
    """上一段对话是否已经结束：空闲超过 IDLE_MINUTES，且这一段真的说过话。

    两条件缺一不可：
    - 没说满一轮的空片段直接复用，不算「聊过」；
    - 缺少时间戳时按「刚说过」处理，宁可不断段也不误判。
    """
    if not turn_count or last_active_at is None:
        return False
    idle_minutes = (now - last_active_at).total_seconds() / 60
    return idle_minutes > IDLE_MINUTES
