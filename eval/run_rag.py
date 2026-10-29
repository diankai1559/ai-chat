"""跑 RAG 版对话：134 轮切成 13 天，每天约 10 轮，按天落段。

和摘要版严格对齐：
- 同一份对话脚本、同一个提示词模板、同一温度
- 记忆预算都是 800 字（画像 200 + 3 段召回 200）
- 最近窗口都是 6 条
- 消息只在内存里，不写库

用法：
    python -m eval.run_rag
    python -m eval.run_rag --days 2 --limit 22   # 小样本试跑
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from app.infrastructure import usage
from app.config import CHAT_TEMPERATURE, MEMORY_CHAR_BUDGET
from app.infrastructure.llm import chat_stream
from app.infrastructure.memory import MemoryStore, Segment, summarize_segment, update_profile
from app.infrastructure.memory.embeddings import embed_texts
from app.infrastructure.memory.build import memory_budget_report
from app.application.prompt import PROMPT_VERSION, template_fingerprint
from app.application.state import EmotionState, advance
from app.application.chat_service import Messages

from eval.run_baseline import load_turns, stream_reply

HERE = Path(__file__).resolve().parent
DIALOGUE = HERE / "dialogue.txt"
RESULT_DIR = HERE / "results"


def split_days(turns: list[dict], days: int) -> list[list[dict]]:
    """尽量均分：134 / 13 = 10 余 4，前 4 天各 11 轮，其余 10 轮。"""
    base, extra = divmod(len(turns), days)
    sizes = [base + 1] * extra + [base] * (days - extra)
    out, index = [], 0
    for size in sizes:
        out.append(turns[index:index + size])
        index += size
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=13)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 天")
    parser.add_argument("--min-wait", type=float, default=0.5)
    parser.add_argument("--max-wait", type=float, default=1.2)
    args = parser.parse_args()

    api_key = os.getenv("EVAL_API_KEY")
    if not api_key:
        sys.exit("缺少 EVAL_API_KEY")

    turns = load_turns(DIALOGUE)
    days = split_days(turns, args.days)
    if args.limit:
        days = days[: args.limit]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    store = MemoryStore()
    m = Messages(user_id=0, persist=False, mode="rag", memory=store)
    m.state = EmotionState()
    start = datetime.now()

    transcript: list[dict] = []
    day_logs: list[dict] = []
    usage_before = usage.totals()

    print(
        f"RAG 版：{sum(len(d) for d in days)} 轮 / {len(days)} 天，"
        f"{PROMPT_VERSION} / {template_fingerprint()}",
        flush=True,
    )

    for day_index, day_turns in enumerate(days, start=1):
        m.now = start + timedelta(days=day_index - 1)
        # 新的一天 = 新会话，但记忆和状态延续
        m.messages = []
        m.ensure_system(query=day_turns[0]["text"])

        day_messages: list[dict] = []
        for item in day_turns:
            m.messages.append({"id": None, "role": "user", "content": item["text"]})
            m.ensure_system(query=item["text"])
            context = m.get_context()

            try:
                reply = stream_reply(context, api_key)
            except Exception as exc:
                print(f"[day {day_index} turn {item['turn']}] 失败: {exc}", flush=True)
                reply = ""
            if not reply:
                print(f"[day {day_index} turn {item['turn']}] 空回复，跳过", flush=True)
                m.messages.pop()
                continue

            m.messages.append({"id": None, "role": "assistant", "content": reply})
            m.save_messages()
            m.state = advance(m.state, item["text"], reply, now=m.now, api_key=api_key)

            day_messages.append({"role": "user", "content": item["text"]})
            day_messages.append({"role": "assistant", "content": reply})
            transcript.append({
                "day": day_index,
                "turn": item["turn"],
                "tag": item["tag"],
                "user": item["text"],
                "assistant": reply,
                "emotion": m.state.render_emotion(),
            })
            print(
                f"[D{day_index:02d} {item['turn']:03d}] {item['tag']:>6s} "
                f"状态={m.state.render_emotion()}",
                flush=True,
            )
            time.sleep(random.uniform(args.min_wait, args.max_wait))

        # 一天结束：压成 200 字片段，入库，再滚动更新 200 字画像
        summary = summarize_segment(day_messages, api_key=api_key)
        embedding = None
        vectors = embed_texts([summary]) if summary else None
        if vectors:
            embedding = vectors[0]
        store.add(Segment(
            day=day_index,
            start_turn=day_turns[0]["turn"],
            end_turn=day_turns[-1]["turn"],
            summary=summary,
            embedding=embedding,
        ))
        store.profile = update_profile(store.profile, summary, api_key=api_key)

        day_logs.append({
            "day": day_index,
            "turns": len(day_turns),
            "segment_summary": summary,
            "segment_chars": len(summary),
            "profile": store.profile,
            "profile_chars": len(store.profile),
        })
        print(
            f"  day {day_index} 落段 {len(summary)} 字 / 画像 {len(store.profile)} 字",
            flush=True,
        )

    finished = datetime.now()
    elapsed = (finished - start).total_seconds()
    recent = m.get_context()[1:]
    retrieved = store.search(recent[-1]["content"] if recent else "", top_k=3)

    payload = {
        "mode": "rag",
        "prompt_version": PROMPT_VERSION,
        "template_fingerprint": template_fingerprint(),
        "model": "deepseek-flash",
        "temperature": CHAT_TEMPERATURE,
        "turns_done": len(transcript),
        "days_done": len(day_logs),
        "started_at": start.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "profile": store.profile,
        "memory": store.to_dict(),
        "recent_messages": recent,
        "state": {
            "emotion": m.state.emotion,
            "intensity": round(m.state.intensity, 2),
            "closeness": round(m.state.closeness, 2),
            "rendered_emotion": m.state.render_emotion(),
            "rendered_relationship": m.state.render_relationship(),
        },
        "budget": memory_budget_report(store.profile, retrieved),
        "day_logs": day_logs,
        "usage": {
            kind: {k: v - usage_before.get(kind, {}).get(k, 0) for k, v in value.items()}
            for kind, value in usage.totals().items()
        },
        "transcript": transcript,
    }

    json_path = RESULT_DIR / f"RAG版_对话记录_{len(transcript)}轮_{stamp}.json"
    txt_path = RESULT_DIR / f"RAG版_对话记录_{len(transcript)}轮_{stamp}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for row in transcript:
        lines.append(f"[第{row['day']}天 {row['turn']:03d}轮] 林夏：{row['user']}")
        lines.append(f"[第{row['day']}天 {row['turn']:03d}轮] 小满：{row['assistant']}")
    lines += ["", "===== 最终画像 =====", store.profile or "（空）", "", "===== 13 段记忆 ====="]
    for log in day_logs:
        lines.append(f"[第{log['day']}天 {log['turns']}轮] {log['segment_summary']}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"完成 {len(transcript)} 轮 / {len(day_logs)} 天，用时 {elapsed:.0f}s", flush=True)
    print(f"画像 {len(store.profile)} 字，预算 {payload['budget']}", flush=True)
    print(f"结果：{json_path}", flush=True)
    print(f"对话：{txt_path}", flush=True)


if __name__ == "__main__":
    main()
