"""情绪 / 关系状态的更新回路：高温说话，低温提取。

主模型（较高温度、流式）负责把情绪说出来；副模型（温度 0）把这一轮的表达抽成
结构化 JSON，写回 user_states，下一轮再注入提示词。完成品就是这个架构，
评测阶段照原样跑，避免"评测用的是一套、上线是另一套"。

公平性约束（改动前务必读）：
1. 四组条件共用本文件，同模型、同温度、同提示词，只在记忆槽上有差别；
2. 提取器只能看到「上一轮状态 + 用户这条消息 + 她自己这条回复」，
   绝不能看到检索到的记忆或会话摘要，否则记忆会顺着情绪泄漏进基线组；
3. 注入提示词时只给定性描述（"有点低落"），不注入数字和提取理由。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime

from .db import SessionLocal, UserState
from .llm import chat_json

EMOTIONS = ("开心", "平静", "低落", "焦虑", "生气", "疲惫", "亲近", "兴奋")

# 情绪的基线强度：长期没互动会回落到这里，但不等于"她一直是平静的"
BASE_INTENSITY = 0.2
FLOOR_INTENSITY = 0.15


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class EmotionState:
    emotion: str = ""             # 空表示还没形成状态，只有提取器才能填
    intensity: float = 0.0
    closeness: float = 0.4        # 关系亲密度，变化比情绪慢得多
    updated_at: datetime = field(default_factory=datetime.now)

    def render_emotion(self) -> str:
        """渲染成人话，不暴露数值。"""
        if not self.emotion:
            return "（还没成形，刚聊起来）"
        if self.emotion == "平静" or self.intensity < 0.25:
            return "平静"
        return ("有点" if self.intensity < 0.55 else "很") + self.emotion

    def render_relationship(self) -> str:
        if self.closeness < 0.3:
            return "刚认识，还不太熟"
        if self.closeness < 0.55:
            return "认识一段时间的朋友"
        if self.closeness < 0.8:
            return "比较熟的朋友"
        return "很亲近的老朋友"

    def to_prompt_fields(self) -> tuple[str, str]:
        return self.render_emotion(), self.render_relationship()


def decayed(state: EmotionState, now: datetime | None = None,
            half_life_hours: float = 12.0) -> EmotionState:
    """按 exp(-Δt/τ) 向基线回落；关系亲密度不随时间衰减。"""
    now = now or datetime.now()
    hours = (now - state.updated_at).total_seconds() / 3600
    if hours <= 0:
        return state
    factor = 0.5 ** (hours / half_life_hours)
    intensity = FLOOR_INTENSITY + (state.intensity - FLOOR_INTENSITY) * factor
    emotion = state.emotion
    if intensity < 0.25:
        emotion = "平静" if state.emotion else ""
    return replace(state, emotion=emotion, intensity=intensity, updated_at=now)


EXTRACT_PROMPT = """你是一个状态提取器。只更新对话角色「小满」自己的状态，不做别的事。

【上一轮状态】
情绪：{prev_emotion}
情绪强度：{prev_intensity}
关系亲密度：{prev_closeness}

【用户这条消息】
{user_message}

【小满这条回复】
{assistant_reply}

只输出一个 JSON 对象，不要解释、不要代码块：
{{"emotion": "开心", "intensity": 0.6, "closeness": 0.45}}

规则：
1. emotion 只能从「开心、平静、低落、焦虑、生气、疲惫、亲近、兴奋」里选一个。
2. intensity 是情绪强度，0 表示几乎没有，1 表示非常强烈；多数时候应落在 0.2~0.6。
3. closeness 是关系亲密度，取值 0~1，单轮变化不超过 0.1。
4. 你提取的是小满自己的状态，不是用户的情绪。用户难过时她可能心疼、低落，但不是在替用户难过；用户夸她时她会开心，但不要每句都升温。
5. 这一轮没有明显情绪变化时，让 intensity 向 0.2 回落，而不是保持不变。
6. 不要引入这两段文字里没有出现过的信息。
"""


def extract_state(prev: EmotionState, user_message: str, assistant_reply: str,
                  api_key=None) -> EmotionState:
    """用低温度副模型把这一轮的状态抽出来；失败就沿用上一轮，绝不阻塞对话。"""
    prompt = EXTRACT_PROMPT.format(
        prev_emotion=prev.render_emotion(),
        prev_intensity=f"{prev.intensity:.2f}",
        prev_closeness=f"{prev.closeness:.2f}",
        user_message=user_message.strip()[:600],
        assistant_reply=assistant_reply.strip()[:800],
    )
    data = chat_json(
        [{"role": "user", "content": prompt}],
        api_key=api_key, temperature=0.0, max_tokens=120,
    )
    if not isinstance(data, dict):
        return replace(prev, updated_at=datetime.now())

    emotion = data.get("emotion")
    if emotion not in EMOTIONS:
        emotion = prev.emotion

    if emotion == "平静":
        intensity = min(_as_float(data.get("intensity"), prev.intensity), 0.3)
    else:
        intensity = _clamp(_as_float(data.get("intensity"), prev.intensity))

    # 关系变化要慢，单轮最多 ±0.1，避免一轮对话就"变成最亲近的朋友"
    closeness = _clamp(
        _as_float(data.get("closeness"), prev.closeness),
        prev.closeness - 0.1, prev.closeness + 0.1,
    )

    return EmotionState(
        emotion=emotion,
        intensity=intensity,
        closeness=closeness,
        updated_at=datetime.now(),
    )


def advance(prev: EmotionState, user_message: str, assistant_reply: str,
            now: datetime | None = None, api_key=None) -> EmotionState:
    """一轮结束后的状态推进：先按时间衰减，再按这一轮表现更新。

    在回复流结束后调用（和 maybe_summarize 同一个后台线程位置），
    不占用首 token 的时间。
    """
    state = decayed(prev, now=now)
    new_state = extract_state(state, user_message, assistant_reply, api_key=api_key)
    if now is not None:
        new_state.updated_at = now
    return new_state


def load_state(user_id: int) -> EmotionState:
    """读取用户的持久化状态；没有记录时返回初始状态。"""
    with SessionLocal() as db:
        row = db.get(UserState, user_id)
        if row is None:
            return EmotionState()
        return EmotionState(
            emotion=row.emotion or "",
            intensity=row.intensity if row.intensity is not None else 0.0,
            closeness=row.closeness if row.closeness is not None else 0.4,
            updated_at=row.updated_at or datetime.now(),
        )


def save_state(user_id: int, state: EmotionState) -> None:
    with SessionLocal() as db:
        row = db.get(UserState, user_id)
        if row is None:
            row = UserState(user_id=user_id)
            db.add(row)
        row.emotion = state.emotion
        row.intensity = state.intensity
        row.closeness = state.closeness
        row.updated_at = state.updated_at
        db.commit()
