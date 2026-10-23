"""最终版：真实场景对话 —— 一个话题聊几轮就结束，结束即写入知识库。

真实用户一次只说一件事，所以每个场景是一个话题、3 轮左右，场景之间视为
"30 分钟没有新消息"而结束：窗口清空、片段入库、画像更新。
100 个场景 = 100 个记忆片段，检索粒度比"一天一段"更细。

用法：
    python -m eval.run_final
    python -m eval.run_final --limit 10   # 先跑 10 个场景
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

from app import usage
from app.config import CHAT_TEMPERATURE
from app.memory import MemoryStore, Segment, summarize_segment, update_profile
from app.memory.build import memory_budget_report
from app.memory.embeddings import embed_texts
from app.prompt import PROMPT_VERSION, template_fingerprint
from app.state import EmotionState, advance
from app.storage import Messages

from eval.run_baseline import stream_reply

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "dialogue_real.txt"
RESULT_DIR = HERE / "results"


def load_scenes(path: Path) -> list[dict]:
    scenes: list[dict] = []
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# S") and "|" in line:
            parts = [p.strip() for p in line[2:].split("|")]
            current = {
                "id": parts[0],
                "fact": parts[1],
                "topic": parts[2] if len(parts) > 2 else "",
                "lines": [],
            }
            scenes.append(current)
        elif line == "---":
            current = None
        elif line and not line.startswith("#") and current is not None:
            current["lines"].append(line)
    return scenes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-wait", type=float, default=0.3)
    parser.add_argument("--max-wait", type=float, default=0.8)
    args = parser.parse_args()

    api_key = os.getenv("EVAL_API_KEY")
    if not api_key:
        sys.exit("缺少 EVAL_API_KEY")

    scenes = load_scenes(SCRIPT)
    if args.limit:
        scenes = scenes[: args.limit]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    store = MemoryStore()
    m = Messages(user_id=0, persist=False, mode="rag", memory=store)
    m.state = EmotionState()
    start = datetime.now()

    transcript: list[dict] = []
    scene_logs: list[dict] = []
    turn_map: dict[str, int] = {}
    usage_before = usage.totals()
    global_turn = 0

    print(
        f"最终版：{len(scenes)} 个场景，{PROMPT_VERSION} / {template_fingerprint()}",
        flush=True,
    )

    for scene_index, scene in enumerate(scenes, start=1):
        # 场景之间视为间隔 45 分钟（>30 分钟），新场景重新开会话
        m.now = start + timedelta(minutes=45 * (scene_index - 1))
        m.messages = []
        m.ensure_system(query=scene["lines"][0])

        scene_messages: list[dict] = []
        first_turn = global_turn + 1

        for line_index, text in enumerate(scene["lines"]):
            global_turn += 1
            if line_index == 1:
                turn_map[scene["fact"]] = global_turn

            m.messages.append({"id": None, "role": "user", "content": text})
            m.ensure_system(query=text)
            context = m.get_context()

            try:
                reply = stream_reply(context, api_key)
            except Exception as exc:
                print(f"[{scene['id']}] 失败: {exc}", flush=True)
                reply = ""
            if not reply:
                print(f"[{scene['id']}] 空回复，跳过该句", flush=True)
                m.messages.pop()
                continue

            m.messages.append({"id": None, "role": "assistant", "content": reply})
            m.save_messages()
            m.state = advance(m.state, text, reply, now=m.now, api_key=api_key)

            scene_messages.append({"role": "user", "content": text})
            scene_messages.append({"role": "assistant", "content": reply})
            transcript.append({
                "scene": scene_index,
                "turn": global_turn,
                "fact": scene["fact"],
                "user": text,
                "assistant": reply,
            })
            print(
                f"[{scene['id']} {scene['fact']}] {text[:14]}… 状态={m.state.render_emotion()}",
                flush=True,
            )
            time.sleep(random.uniform(args.min_wait, args.max_wait))

        # 场景结束：这一件事写成一段 ≤200 字记忆，入库并更新画像
        summary = summarize_segment(scene_messages, api_key=api_key)
        vectors = embed_texts([summary]) if summary else None
        store.add(Segment(
            day=scene_index,
            start_turn=first_turn,
            end_turn=global_turn,
            summary=summary,
            embedding=vectors[0] if vectors else None,
        ))
        store.profile = update_profile(store.profile, summary, api_key=api_key)

        scene_logs.append({
            "scene": scene_index,
            "id": scene["id"],
            "fact": scene["fact"],
            "topic": scene["topic"],
            "turns": len(scene["lines"]),
            "summary": summary,
            "summary_chars": len(summary),
            "profile_chars": len(store.profile),
        })
        print(
            f"  {scene['id']} 落段 {len(summary)} 字 / 画像 {len(store.profile)} 字",
            flush=True,
        )

    finished = datetime.now()
    elapsed = (finished - start).total_seconds()
    recent = m.get_context()[1:]
    retrieved = store.search(recent[-1]["content"] if recent else "", top_k=3)

    payload = {
        "mode": "rag",
        "variant": "final_scene",
        "script": SCRIPT.name,
        "prompt_version": PROMPT_VERSION,
        "template_fingerprint": template_fingerprint(),
        "model": "deepseek-flash",
        "temperature": CHAT_TEMPERATURE,
        "turns_done": len(transcript),
        "scenes_done": len(scene_logs),
        "started_at": start.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "turn_map": turn_map,
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
        "scene_logs": scene_logs,
        "usage": {
            kind: {k: v - usage_before.get(kind, {}).get(k, 0) for k, v in value.items()}
            for kind, value in usage.totals().items()
        },
        "transcript": transcript,
    }

    json_path = RESULT_DIR / f"RAG最终版_对话记录_{len(scene_logs)}段_{stamp}.json"
    txt_path = RESULT_DIR / f"RAG最终版_对话记录_{len(scene_logs)}段_{stamp}.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = []
    for row in transcript:
        lines.append(f"[场景{row['scene']:03d} 第{row['turn']:03d}轮] 林夏：{row['user']}")
        lines.append(f"[场景{row['scene']:03d} 第{row['turn']:03d}轮] 小满：{row['assistant']}")
    lines += ["", "===== 最终画像 =====", store.profile or "（空）", "", "===== 记忆片段 ====="]
    for log in scene_logs:
        lines.append(f"[{log['id']} {log['topic']}] {log['summary']}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"完成 {len(transcript)} 轮 / {len(scene_logs)} 个场景，用时 {elapsed:.0f}s", flush=True)
    print(f"画像 {len(store.profile)} 字，预算 {payload['budget']}", flush=True)
    print(f"结果：{json_path}", flush=True)
    print(f"对话：{txt_path}", flush=True)


if __name__ == "__main__":
    main()
