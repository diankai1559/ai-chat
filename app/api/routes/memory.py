"""记忆大脑接口：把长期记忆整理成前端可视化用的数据。

这里只做「取数据 + 统一字段」，不做任何摆位与分组：
分组方式（话题/人物/地点/情绪）是展示层的选择，放在 static/js/brain.js 里。
"""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ...infrastructure import repositories as repo
from ...infrastructure.db import User

router = APIRouter()


def _segment_item(row: dict) -> dict:
    """把一条已关闭片段翻译成前端需要的字段；时间统一成字符串和秒数。"""
    ended = row["ended_at"]
    return {
        "seq": row["seq"],
        "summary": row["summary"],
        "tags": row["tags"] or {},
        "turns": row["turn_count"],
        "day": ended.strftime("%Y-%m-%d") if ended else "",
        "ts": int(ended.timestamp()) if ended else 0,
    }


@router.get("/memory/graph")
def memory_graph(user: User = Depends(get_current_user)):
    """当前用户的常驻画像 + 全部已关闭片段，供记忆大脑页绘图。"""
    profile = repo.load_profile(user.id)
    rows = repo.closed_segments(user.id)

    # 没压出摘要的片段没有回忆价值，不参与可视化
    items = [_segment_item(row) for row in rows if row["summary"]]

    return {
        "profile": profile,
        "segments": items,
        "stats": {
            "segments": len(items),
            "days": len({item["day"] for item in items if item["day"]}),
            "profile_chars": len(profile),
        },
    }
