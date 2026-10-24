"""把一天的对话压成 200 字记忆，并滚动更新 200 字长期画像。

预算约束：画像 200 + 3 段召回 200 = 800 字，和摘要版的一份 800 字摘要等价。
"""

from __future__ import annotations

from ..config import MEMORY_CHAR_BUDGET, SEGMENT_CHAR_LIMIT
from ..llm import chat, chat_json

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


SEGMENT_JSON_PROMPT = """把这一天的对话压成一段记忆并打标签，只输出一个 JSON 对象，不要解释。

格式：
{{"summary": "事实：...\\n事件：...\\n待办：...", "tags": {{"time": "", "place": "", "people": [], "emotion": "", "topic": "", "open_loops": [], "importance": 0.5}}}}

规则：
1. summary 只写用户明确说过的内容，不推断、不编造；按事实/事件/待办三行写，最多 {max_chars} 字。
2. time 写对话里出现的时间线索（如"去年十月""上周""今天"），没有就空字符串。
3. place 写出现的地点，没有就空字符串。
4. people 写对话里提到的其他人（用户本人不用写），没有就空数组。
5. emotion 只能从「开心、平静、低落、焦虑、生气、疲惫、亲近、兴奋」里选一个，判断用户当时的情绪。
6. topic 用 1~2 个词概括话题，例如"工作/跳槽"。
7. open_loops 写用户提到但还没完成的事，没有就空数组。
8. importance 取 0~1，长期事实和生活事件给高一点，闲聊给低一点。

【对话】
{dialogue}
"""


def _normalize_tags(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out = {
        "time": str(raw.get("time") or "")[:30],
        "place": str(raw.get("place") or "")[:30],
        "emotion": str(raw.get("emotion") or "")[:10],
        "topic": str(raw.get("topic") or "")[:30],
    }
    for key in ("people", "open_loops"):
        value = raw.get(key)
        out[key] = [str(x)[:20] for x in value[:5] if x] if isinstance(value, list) else []
    try:
        out["importance"] = max(0.0, min(1.0, float(raw.get("importance", 0.5))))
    except (TypeError, ValueError):
        out["importance"] = 0.5
    return out


def summarize_segment_tagged(turns: list[dict], api_key=None) -> tuple[str, dict]:
    """一次调用同时产出摘要和标签；失败时退回纯文本摘要 + 空标签。"""
    dialogue = "\n".join(
        f"{'用户' if t['role'] == 'user' else '小满'}：{t['content']}" for t in turns
    )
    prompt = SEGMENT_JSON_PROMPT.format(max_chars=SEGMENT_CHAR_LIMIT, dialogue=dialogue)
    data = chat_json(
        [{"role": "user", "content": prompt}],
        api_key=api_key, temperature=0.0, max_tokens=600,
    )
    if not isinstance(data, dict):
        return summarize_segment(turns, api_key=api_key), {}

    summary = str(data.get("summary") or "").strip()[:SEGMENT_CHAR_LIMIT]
    if not summary:
        summary = summarize_segment(turns, api_key=api_key)
    return summary, _normalize_tags(data.get("tags"))


TAGS_ONLY_PROMPT = """从下面这段对话里提取结构化标签，只输出 JSON：
{{"time": "", "place": "", "people": [], "emotion": "", "topic": "", "open_loops": [], "importance": 0.5}}

规则：
1. time 写对话里出现的时间线索，没有就空字符串。
2. place 写出现的地点，没有就空字符串。
3. people 写对话里提到的其他人（用户本人不用写），没有就空数组。
4. emotion 只能从「开心、平静、低落、焦虑、生气、疲惫、亲近、兴奋」里选一个。
5. topic 用 1~2 个词概括话题。
6. open_loops 写用户提到但还没完成的事，没有就空数组。
7. importance 取 0~1。

【对话】
{dialogue}
"""


def extract_tags(turns: list[dict], api_key=None) -> dict:
    """只提取标签，不改写已有摘要（用于给历史片段补标签）。"""
    dialogue = "\n".join(
        f"{'用户' if t['role'] == 'user' else '小满'}：{t['content']}" for t in turns
    )
    data = chat_json(
        [{"role": "user", "content": TAGS_ONLY_PROMPT.format(dialogue=dialogue)}],
        api_key=api_key, temperature=0.0, max_tokens=300,
    )
    return _normalize_tags(data)


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
