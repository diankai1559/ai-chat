"""人设提示词：生产运行与评测共用同一份。

公平性约定（不要再随意改动）：
1. 固定骨架（人设 + 槽位标题 + 说话规则）不超过 400 字；
2. 可注入的记忆总量固定 800 字：
   - 原版：一份不超过 800 字的摘要
   - 最终版：最多 4 份、每份约 200 字（常驻画像占 1 份，召回片段占 3 份）
   两者合计 1200 字，后期记忆填满后输入量也一致；
3. 情绪 / 关系两个状态槽两边完全相同，属于公共输入，不计入差异；
4. 记忆差异只体现在槽位内容上，空槽位统一渲染为 EMPTY，不改变任何措辞；
5. 提示词不出现「记忆 / 知识库 / 检索 / 摘要 / 上下文」等机制词；
6. 任何修改都必须提升 PROMPT_VERSION 并重跑全部基线，否则历史结果不可比。
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from .config import BASE_PROMPT_CHARS, MEMORY_CHAR_BUDGET, SEGMENT_CHAR_LIMIT, SEGMENT_COUNT

PROMPT_VERSION = "persona-v4"

# 空槽位的统一渲染，四组条件必须完全一致
EMPTY = "（无）"

# 仅第一轮使用：此时还没有产生过任何状态，不能假装她已经平静
INITIAL_EMOTION = "（还没成形，刚聊起来）"
INITIAL_RELATIONSHIP = "（刚认识，还不太熟）"

PERSONA_NAME = "小满"

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

PERSONA_PROMPT = """你是「{name}」，用户的老朋友，不是客服也不是工具。

【当前时间】{now}
【记得的事】
- 较早的对话：{earlier_summary}
- 相关的往事：{related_memories}
- 长期情况：{user_profile}
【当前状态】情绪：{emotion}；关系：{relationship}

【怎么说话】
1. 先正面回答，通常 1~4 句。
2. 只知道上面这些和本次对话，其余都不知道。
3. 问具体日期、地点、人名、数字，上面没有就说「你没跟我提过」，不猜不编。
4. 回顾性问题先看「较早的对话」。
5. 信息冲突以更近的为准。
6. 不问用户已经说过的。
7. 像朋友：口语、有态度，不奉承。
8. 细节自然说，不念清单。
9. 不提「记忆」「知识库」「检索」「摘要」。
10. 专业问题说明自己不是专业人士。
"""


def format_now(dt: datetime | None = None) -> str:
    """把时间渲染成提示词里的形态，避免不同条件下格式不一致。"""
    dt = dt or datetime.now()
    return f"{dt.year}年{dt.month}月{dt.day}日 {_WEEKDAYS[dt.weekday()]} {dt:%H:%M}"


def compose_memory(
    *,
    summary: str | None = None,
    profile: str | None = None,
    segments: list[str] | None = None,
) -> tuple[str, str, str]:
    """按统一预算组装三个记忆槽，返回 (较早的对话, 相关的往事, 长期情况)。

    - 原版：summary 一份，最多 800 字
    - 最终版：profile 一份（200 字）+ 召回片段（每份 200 字），合计最多 800 字
    两套预算相同，后期记忆填满后送入模型的记忆量一致。
    """
    if summary:
        return (summary.strip()[:MEMORY_CHAR_BUDGET], "", "")

    profile_text = (profile or "").strip()[:SEGMENT_CHAR_LIMIT]
    budget = MEMORY_CHAR_BUDGET - len(profile_text)
    blocks = [s.strip()[:SEGMENT_CHAR_LIMIT] for s in (segments or []) if s and s.strip()]
    blocks = blocks[:SEGMENT_COUNT - 1] if profile_text else blocks[:SEGMENT_COUNT]
    return ("", "\n".join(blocks)[:budget], profile_text)


def build_system_prompt(
    *,
    now: datetime | str | None = None,
    summary: str | None = None,
    profile: str | None = None,
    segments: list[str] | None = None,
    emotion: str | None = None,
    relationship: str | None = None,
) -> str:
    """按固定槽位拼出 system 提示词。

    四个评测组都用这个函数，区别只在记忆槽传不传内容：
    - B0 纯窗口：三槽全空
    - B1 现状：只传 summary
    - B2 / B3：传 profile + segments，由 compose_memory 统一裁到 800 字

    情绪 / 关系四组都必须传，由 app/state.py 每轮产出；
    只有第一轮才允许为空（渲染成「还没成形」），不能默认写成「平静」。
    """
    earlier_summary, related_memories, user_profile = compose_memory(
        summary=summary, profile=profile, segments=segments
    )
    values = {
        "name": PERSONA_NAME,
        "now": now if isinstance(now, str) else format_now(now),
        "earlier_summary": earlier_summary or EMPTY,
        "related_memories": related_memories or EMPTY,
        "user_profile": user_profile or EMPTY,
        "emotion": emotion or INITIAL_EMOTION,
        "relationship": relationship or INITIAL_RELATIONSHIP,
    }

    text = PERSONA_PROMPT
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def prompt_stats() -> dict[str, int | bool]:
    """检查固定骨架是否守住了 400 字上限。"""
    fixed = len(build_system_prompt())
    return {
        "fixed_chars": fixed,
        "fixed_limit": BASE_PROMPT_CHARS,
        "fixed_ok": fixed <= BASE_PROMPT_CHARS,
        "memory_budget": MEMORY_CHAR_BUDGET,
        "segment_chars": SEGMENT_CHAR_LIMIT,
        "segment_count": SEGMENT_COUNT,
    }


def template_fingerprint() -> str:
    """模板指纹，与槽位内容无关。公平性以这个为准，因为渲染后的文本每轮都不同。"""
    return hashlib.sha256((PROMPT_VERSION + PERSONA_PROMPT).encode("utf-8")).hexdigest()[:16]


def prompt_fingerprint(text: str) -> str:
    """渲染后文本的指纹，仅用于排查某轮实际发了什么，不作为公平性证据。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
