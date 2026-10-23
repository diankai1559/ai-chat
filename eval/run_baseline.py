"""跑一遍基线（摘要版）对话，不写数据库、不碰 Redis。

消息和回复只在内存里的 Messages 实例中流转（persist=False），
跑完把完整对话、最终摘要、最终状态和上下文快照写到 eval/results/，
下一步的提问脚本直接读这份快照，保证问的是同一段对话。

用法：
    python -m eval.run_baseline              # 跑完整脚本
    python -m eval.run_baseline --limit 20   # 先跑 20 轮试水
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from app import usage
from app.config import CHAT_TEMPERATURE
from app.llm import chat_stream
from app.prompt import PROMPT_VERSION, template_fingerprint
from app.state import EmotionState, advance
from app.storage import Messages

HERE = Path(__file__).resolve().parent
DIALOGUE = HERE / "dialogue.txt"
RESULT_DIR = HERE / "results"

LINE_RE = re.compile(r"^(\d{3})\s*\|\s*([FN]\d*)(?:\s+[^|]*)?\s*\|\s*(.+?)\s*$")


def load_turns(path: Path) -> list[dict]:
    turns = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = LINE_RE.match(line)
        if not match:
            print(f"跳过无法解析的行: {line}", flush=True)
            continue
        turns.append({
            "turn": int(match.group(1)),
            "tag": match.group(2),
            "text": match.group(3),
        })
    return turns


def stream_reply(context: list[dict], api_key: str) -> str:
    parts: list[str] = []
    for chunk in chat_stream(context, api_key=api_key, temperature=CHAT_TEMPERATURE):
        if chunk.startswith("data: [ERROR]"):
            raise RuntimeError(chunk.strip())
        if chunk.startswith("data: ") and chunk != "data: [DONE]\n\n":
            parts.append(chunk[6:].rstrip("\n"))
    return "".join(parts).strip()


def usage_delta(before: dict, after: dict) -> dict:
    delta = {}
    for kind, value in after.items():
        old = before.get(kind, {})
        delta[kind] = {k: v - old.get(k, 0) for k, v in value.items()}
    return delta


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 轮，0 表示全部")
    parser.add_argument("--min-wait", type=float, default=2.0)
    parser.add_argument("--max-wait", type=float, default=4.0)
    args = parser.parse_args()

    api_key = os.getenv("EVAL_API_KEY")
    if not api_key:
        sys.exit("缺少 EVAL_API_KEY：先在 .env 里配置专用测试 Key")

    turns = load_turns(DIALOGUE)
    if args.limit:
        turns = turns[: args.limit]
    if not turns:
        sys.exit("dialogue.txt 里没有可用的对话行")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    m = Messages(user_id=0, persist=False)
    m.state = EmotionState()
    transcript: list[dict] = []
    started = datetime.now()
    usage_before = usage.totals()

    print(f"开始跑 {len(turns)} 轮，提示词 {PROMPT_VERSION} / {template_fingerprint()}", flush=True)

    for item in turns:
        m.messages.append({"id": None, "role": "user", "content": item["text"]})
        m.ensure_system()
        context = m.get_context()

        try:
            reply = stream_reply(context, api_key)
        except Exception as exc:
            print(f"[{item['turn']:03d}] 调用失败: {exc}", flush=True)
            break

        if not reply:
            print(f"[{item['turn']:03d}] 空回复，停止", flush=True)
            break

        m.messages.append({"id": None, "role": "assistant", "content": reply})
        m.save_messages()
        m.maybe_summarize(api_key=api_key)
        m.state = advance(m.state, item["text"], reply, api_key=api_key)
        m.ensure_system()

        transcript.append({
            "turn": item["turn"],
            "tag": item["tag"],
            "user": item["text"],
            "assistant": reply,
            "summary_chars": len(m.summary),
            "emotion": m.state.render_emotion(),
            "relationship": m.state.render_relationship(),
        })
        print(
            f"[{item['turn']:03d}] {item['tag']:>6s} "
            f"记忆={len(m.summary):3d}字 状态={m.state.render_emotion()}",
            flush=True,
        )

        time.sleep(random.uniform(args.min_wait, args.max_wait))

    finished = datetime.now()
    elapsed = (finished - started).total_seconds()

    payload = {
        "prompt_version": PROMPT_VERSION,
        "template_fingerprint": template_fingerprint(),
        "model": "deepseek-flash",
        "temperature": CHAT_TEMPERATURE,
        "persist": False,
        "turns_done": len(transcript),
        "turns_total": len(turns),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "summary": m.summary,
        "summary_chars": len(m.summary),
        "state": {
            "emotion": m.state.emotion,
            "intensity": round(m.state.intensity, 2),
            "closeness": round(m.state.closeness, 2),
            "rendered_emotion": m.state.render_emotion(),
            "rendered_relationship": m.state.render_relationship(),
        },
        "final_context": m.get_context(),
        "usage": usage_delta(usage_before, usage.totals()),
        "transcript": transcript,
    }

    json_path = RESULT_DIR / f"摘要版_对话记录_{len(transcript)}轮_{stamp}.json"
    txt_path = RESULT_DIR / f"摘要版_对话记录_{len(transcript)}轮_{stamp}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for row in transcript:
        lines.append(f"[{row['turn']:03d}] 林夏：{row['user']}")
        lines.append(f"[{row['turn']:03d}] 小满：{row['assistant']}")
    lines.append("")
    lines.append("===== 最终摘要 =====")
    lines.append(m.summary or "（空）")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"完成 {len(transcript)} 轮，用时 {elapsed:.0f}s", flush=True)
    print(f"摘要 {len(m.summary)} 字，上下文 {len(payload['final_context'])} 条", flush=True)
    print(f"结果：{json_path}", flush=True)
    print(f"对话：{txt_path}", flush=True)


if __name__ == "__main__":
    main()
