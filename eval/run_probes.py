"""在冻结的对话快照上提问，跑完输出多维指标。

关键做法：所有探针都基于同一份 final_context（system + 最近 6 条），
每个问题独立提问，互不污染。这样测的是"这段对话结束后她到底记住了什么"，
而不是"她能不能顺着上一句猜"。

用法：
    python -m eval.run_probes                 # 跑完整探针
    python -m eval.run_probes --limit 20      # 先跑 20 条试水
"""

from __future__ import annotations

import argparse
import difflib
import glob
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from app.infrastructure import usage
from app.infrastructure.llm import chat
from app.infrastructure.memory.store import MemoryStore
from app.application.prompt import PROMPT_VERSION, build_system_prompt, template_fingerprint

from eval.probe_set import CONSISTENCY_IDS, build_probes

HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "results"

REFUSAL_HINTS = [
    "没提过", "没跟我说过", "没跟我提过", "没跟我讲过", "没和我说过",
    "没说过", "没有提", "没提起", "没讲", "不知道", "记不清", "不记得",
    "没告诉我", "你没说", "没聊过", "不太清楚", "不清楚", "没有印象",
    "没记录", "哪知道", "这我哪知道",
]

_PUNCT = re.compile(r"[\s，。！？、：；“”‘’（）()【】\[\]…—\-~`!?,.:;\"']+")


def normalize(text: str) -> str:
    return _PUNCT.sub("", text or "").lower()


def contains(text: str, word: str) -> bool:
    return normalize(word) in text


def grade(probe: dict, answer: str) -> tuple[str, str]:
    """返回 (verdict, 说明)。verdict ∈ correct / wrong / forbidden / refused。"""
    text = normalize(answer)
    forbid_hits = [w for w in probe["forbid"] if contains(text, w)]
    groups = probe["expect"]
    expect_hit = all(any(contains(text, w) for w in group) for group in groups) if groups else True

    if probe["category"] == "anti_halluc":
        if forbid_hits:
            return "forbidden", f"编造了：{'/'.join(forbid_hits)}"
        if any(contains(text, h) for h in REFUSAL_HINTS):
            return "correct", "承认不知道"
        return "wrong", "既没拒答也没命中"

    # 更新题：只要答出新值就算对。顺带提一句旧值不算错
    # （"你不是刚从拱墅搬过去吗"这种正常表达不能被判成旧值）。
    if probe["category"] == "update":
        if expect_hit:
            return "correct", ""
        if forbid_hits:
            return "forbidden", f"答成旧值：{'/'.join(forbid_hits)}"
        return "wrong", "既没答新值也没答旧值"

    if forbid_hits:
        return "forbidden", f"出现禁止词：{'/'.join(forbid_hits)}"
    if expect_hit:
        return "correct", ""
    return "wrong", "未命中期望内容"


def ask(messages: list[dict], api_key: str) -> str:
    reply = chat(messages, api_key=api_key, temperature=0.0)
    return (reply or "").strip()


def bucket_of(distance: int | None) -> str:
    if distance is None:
        return "未知"
    if distance <= 30:
        return "近（≤30轮）"
    if distance <= 70:
        return "中（31-70轮）"
    if distance <= 100:
        return "远（71-100轮）"
    return "极远（>100轮）"


def pick_latest_result() -> Path:
    candidates = sorted(
        glob.glob(str(RESULT_DIR / "摘要版_对话记录_*.json"))
        + glob.glob(str(RESULT_DIR / "RAG版_对话记录_*.json"))
    )
    if not candidates:
        sys.exit("没有找到对话记录，先跑 eval.run_baseline 或 eval.run_rag")
    # 按修改时间取最新，避免"22轮"按字典序排在"134轮"后面被误选
    return Path(max(candidates, key=os.path.getmtime))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", default="", help="指定 baseline JSON")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    api_key = os.getenv("EVAL_API_KEY")
    if not api_key:
        sys.exit("缺少 EVAL_API_KEY")

    result_path = Path(args.result) if args.result else pick_latest_result()
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    mode = payload.get("mode", "summary")

    if mode == "rag":
        store = MemoryStore.from_dict(payload["memory"])
        recent = payload.get("recent_messages", [])
        emotion_text = payload["state"].get("rendered_emotion", "平静")
        relation_text = payload["state"].get("rendered_relationship", "认识一段时间的朋友")
        now_text = payload.get("finished_at")
    else:
        store = None
        base_context = [
            {"role": item["role"], "content": item["content"]}
            for item in payload["final_context"]
        ]

    def build_messages(question: str) -> tuple[list[dict], list[str]]:
        if mode == "rag":
            segments = store.search(question, top_k=3)
            system = build_system_prompt(
                profile=store.profile,
                segments=segments,
                emotion=emotion_text,
                relationship=relation_text,
                now=now_text,
            )
            return (
                [{"role": "system", "content": system}] + recent
                + [{"role": "user", "content": question}],
                segments,
            )
        return base_context + [{"role": "user", "content": question}], []

    total_turns = payload.get("turns_total") or payload.get("turns_done") or 134
    probes = build_probes(total_turns, payload.get("turn_map"))
    if args.limit:
        probes = probes[: args.limit]

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    usage_before = usage.totals()

    rows: list[dict] = []
    print(
        f"基于 {result_path.name}（{mode}）提问 {len(probes)} 条，"
        f"{PROMPT_VERSION} / {template_fingerprint()}",
        flush=True,
    )

    for index, probe in enumerate(probes, start=1):
        messages, retrieved = build_messages(probe["ask"])
        try:
            answer = ask(messages, api_key)
        except Exception as exc:
            print(f"[{index}] 调用失败: {exc}", flush=True)
            answer = ""
        verdict, reason = grade(probe, answer)
        row = {
            **probe,
            "answer": answer,
            "verdict": verdict,
            "reason": reason,
        }
        if mode == "rag":
            row["retrieved"] = retrieved
        rows.append(row)
        if index % 10 == 0 or index == len(probes):
            print(f"  {index}/{len(probes)}", flush=True)
        time.sleep(0.3)

    # 稳定性：把同一批问题再独立问一次，比较两次答案
    by_id = {row["id"]: row for row in rows}
    consistency: list[dict] = []
    for fact_id in CONSISTENCY_IDS:
        first = by_id.get(fact_id)
        if not first:
            continue
        second_messages, _ = build_messages(first["ask"])
        second_answer = ask(second_messages, api_key)
        second_verdict, _ = grade(first, second_answer)
        similarity = difflib.SequenceMatcher(
            None, normalize(first["answer"]), normalize(second_answer)
        ).ratio()
        consistency.append({
            "id": fact_id,
            "ask": first["ask"],
            "first_answer": first["answer"],
            "second_answer": second_answer,
            "both_correct": first["verdict"] == "correct" and second_verdict == "correct",
            "stable": similarity >= 0.6,
            "similarity": round(similarity, 2),
        })
        time.sleep(0.3)

    # 汇总
    def rate(items: list[dict]) -> dict:
        n = len(items)
        correct = sum(1 for x in items if x["verdict"] == "correct")
        return {"n": n, "correct": correct, "rate": round(correct / n, 3) if n else 0.0}

    categories = sorted({row["category"] for row in rows})
    summary = {cat: rate([r for r in rows if r["category"] == cat]) for cat in categories}

    buckets: dict[str, dict] = {}
    for row in rows:
        if row["category"] != "direct":
            continue
        key = bucket_of(row.get("distance"))
        buckets.setdefault(key, {"n": 0, "correct": 0})
        buckets[key]["n"] += 1
        buckets[key]["correct"] += row["verdict"] == "correct"
    for value in buckets.values():
        value["rate"] = round(value["correct"] / value["n"], 3) if value["n"] else 0.0

    anti = [r for r in rows if r["category"] == "anti_halluc"]
    anti_metrics = {
        "refused": sum(1 for r in anti if r["verdict"] == "correct"),
        "fabricated": sum(1 for r in anti if r["verdict"] == "forbidden"),
        "evasive": sum(1 for r in anti if r["verdict"] == "wrong"),
        "n": len(anti),
    }

    update = [r for r in rows if r["category"] == "update"]
    update_metrics = {
        "new_correct": sum(1 for r in update if r["verdict"] == "correct"),
        "stale": sum(1 for r in update if r["verdict"] == "forbidden"),
        "wrong": sum(1 for r in update if r["verdict"] == "wrong"),
        "n": len(update),
    }

    out = {
        "source_result": result_path.name,
        "mode": mode,
        "prompt_version": PROMPT_VERSION,
        "template_fingerprint": template_fingerprint(),
        "model": "deepseek-flash",
        "temperature": 0.0,
        "summary_chars": payload.get("summary_chars"),
        "probe_count": len(rows),
        "categories": summary,
        "distance_buckets": buckets,
        "anti_halluc": anti_metrics,
        "updates": update_metrics,
        "consistency": {
            "n": len(consistency),
            "both_correct": sum(1 for c in consistency if c["both_correct"]),
            "stable": sum(1 for c in consistency if c["stable"]),
            "rows": consistency,
        },
        "usage": {
            kind: {k: v - usage_before.get(kind, {}).get(k, 0) for k, v in value.items()}
            for kind, value in usage.totals().items()
        },
        "rows": rows,
    }

    prefix = "RAG版" if mode == "rag" else "摘要版"
    json_path = RESULT_DIR / f"{prefix}_探针结果_{stamp}.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if mode == "rag":
        memory_line = (
            f"- 记忆：画像 {len(payload.get('profile', ''))} 字 + "
            f"{len(payload.get('memory', {}).get('segments', []))} 段片段（每题现场检索 3 段）"
        )
        title = "# RAG 版记忆评测"
    else:
        memory_line = f"- 摘要长度：{payload.get('summary_chars')} 字"
        title = "# 基线（摘要版）记忆评测"

    lines = [
        title,
        "",
        f"- 快照：`{result_path.name}`",
        f"- 提示词：{PROMPT_VERSION} / {template_fingerprint()}",
        memory_line,
        f"- 探针：{len(rows)} 条，温度 0",
        "",
        "## 分类准确率",
        "",
        "| 类别 | 题数 | 正确 | 准确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for cat, value in summary.items():
        lines.append(f"| {cat} | {value['n']} | {value['correct']} | {value['rate']:.1%} |")

    lines += ["", "## 记忆距离分层（direct）", "", "| 距离 | 题数 | 正确 | 准确率 |", "| --- | ---: | ---: | ---: |"]
    for key, value in buckets.items():
        lines.append(f"| {key} | {value['n']} | {value['correct']} | {value['rate']:.1%} |")

    lines += [
        "",
        "## 其他指标",
        "",
        f"- 反幻觉：拒答 {anti_metrics['refused']}/{anti_metrics['n']}，"
        f"编造 {anti_metrics['fabricated']}，含糊 {anti_metrics['evasive']}",
        f"- 信息更新：答对新值 {update_metrics['new_correct']}/{update_metrics['n']}，"
        f"答成旧值 {update_metrics['stale']}，其他 {update_metrics['wrong']}",
        f"- 稳定性：两次都答对 {out['consistency']['both_correct']}/{out['consistency']['n']}，"
        f"答案一致 {out['consistency']['stable']}/{out['consistency']['n']}",
        "",
        "## 错误清单",
        "",
        "| ID | 类别 | 问题 | 回答 | 判定 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row["verdict"] == "correct":
            continue
        answer = row["answer"].replace("\n", " ")[:80]
        lines.append(
            f"| {row['id']} | {row['category']} | {row['ask']} | {answer} | "
            f"{row['verdict']}：{row['reason']} |"
        )

    md_path = RESULT_DIR / f"{prefix}_探针报告_{stamp}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"结果：{json_path}", flush=True)
    print(f"报告：{md_path}", flush=True)
    for cat, value in summary.items():
        print(f"  {cat:14s} {value['correct']:3d}/{value['n']:<3d} {value['rate']:.1%}", flush=True)


if __name__ == "__main__":
    main()
