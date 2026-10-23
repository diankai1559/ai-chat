"""把一天的对话压成 200 字记忆，并滚动更新 200 字长期画像。

预算约束：画像 200 + 3 段召回 200 = 800 字，和摘要版的一份 800 字摘要等价。
"""

from __future__ import annotations

from ..config import MEMORY_CHAR_BUDGET, SEGMENT_CHAR_LIMIT
from ..llm import chat

SEGMENT_PROMPT = """把下面这一天的对话压缩成一段记忆，供以后回忆。

要求：
1. 只写用户明确说过的内容，不推断、不补充、不编造。
2. 按「事实：」「事件：」「待办：」三行写，没有的写「无」。
3. 保留具体的人名、地点、时间、数字、偏好和承诺。
4. 情绪只写用户自己表达过的。
5. 目标 {target_chars} 字左右，最多 {max_chars} 字，尽量写满，别省略人名、地名、数字。
6. 直接输出正文。

【对话】
{dialogue}
"""

PROFILE_PROMPT = """你是长期画像维护器。把【今天的记忆】合并进【已有画像】，输出新的画像。

要求：
1. 只保留稳定信息：身份、家人、工作、住处、长期偏好、长期计划。
2. 一次性的事件、当天的情绪不要写进画像。
3. 新旧冲突时以新信息为准，删掉旧说法。
4. 用第三人称，短句列表，目标 {target_chars} 字左右，最多 {max_chars} 字。
5. 只输出画像正文，不要标题和解释。

【已有画像】
{old_profile}

【今天的记忆】
{segment}
"""


def summarize_segment(turns: list[dict], api_key=None) -> str:
    dialogue = "\n".join(
        f"{'用户' if t['role'] == 'user' else '小满'}：{t['content']}" for t in turns
    )
    prompt = SEGMENT_PROMPT.format(
        target_chars=int(SEGMENT_CHAR_LIMIT * 0.9),
        max_chars=SEGMENT_CHAR_LIMIT,
        dialogue=dialogue,
    )
    reply = chat(
        [{"role": "user", "content": prompt}],
        api_key=api_key, temperature=0.0, kind="segment",
    )
    return (reply or "").strip()[:SEGMENT_CHAR_LIMIT]


def update_profile(old_profile: str, segment: str, api_key=None) -> str:
    prompt = PROFILE_PROMPT.format(
        target_chars=int(SEGMENT_CHAR_LIMIT * 0.9),
        max_chars=SEGMENT_CHAR_LIMIT,
        old_profile=old_profile or "（空）",
        segment=segment,
    )
    reply = chat(
        [{"role": "user", "content": prompt}],
        api_key=api_key, temperature=0.0, kind="profile",
    )
    return (reply or old_profile or "").strip()[:SEGMENT_CHAR_LIMIT]


def memory_budget_report(profile: str, segments: list[str]) -> dict:
    """输出实际占用的字符数，保证和摘要版是同一预算。"""
    used = len(profile) + sum(len(s) for s in segments)
    return {"profile": len(profile), "segments": sum(len(s) for s in segments),
            "used": used, "budget": MEMORY_CHAR_BUDGET, "ok": used <= MEMORY_CHAR_BUDGET}
