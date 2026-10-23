"""Token 用量记录：每次模型调用把 usage 追加到 data/usage.jsonl。

只记 token，不折算金额——价格会变，硬编码容易过时，需要时按当时的单价乘一下即可。

查看汇总：python -m app.usage
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime

from .config import DATA_DIR

USAGE_PATH = DATA_DIR / "usage.jsonl"
_lock = threading.Lock()

DATA_DIR.mkdir(parents=True, exist_ok=True)


def record(kind: str, usage: dict | None) -> None:
    """kind 用来区分主对话、摘要、状态提取，方便看钱花在哪。"""
    if not usage:
        return
    line = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "total_tokens": usage.get("total_tokens", 0) or 0,
        "cache_hit_tokens": usage.get("prompt_cache_hit_tokens", 0) or 0,
        "cache_miss_tokens": usage.get("prompt_cache_miss_tokens", 0) or 0,
    }
    try:
        with _lock, USAGE_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"写入用量日志失败: {e}")


def totals() -> dict[str, dict[str, int]]:
    agg: dict[str, dict[str, int]] = defaultdict(
        lambda: {"calls": 0, "prompt": 0, "completion": 0, "total": 0}
    )
    if not USAGE_PATH.exists():
        return {}
    with USAGE_PATH.open("r", encoding="utf-8") as fh:
        for raw in fh:
            try:
                item = json.loads(raw)
            except ValueError:
                continue
            kind = item.get("kind", "unknown")
            agg[kind]["calls"] += 1
            agg[kind]["prompt"] += item.get("prompt_tokens", 0)
            agg[kind]["completion"] += item.get("completion_tokens", 0)
            agg[kind]["total"] += item.get("total_tokens", 0)
    return dict(agg)


if __name__ == "__main__":
    data = totals()
    if not data:
        print("还没有用量记录")
    for kind, v in data.items():
        print(
            f"{kind:8s} calls={v['calls']:4d} "
            f"prompt={v['prompt']:8d} completion={v['completion']:7d} total={v['total']:8d}"
        )
    print("合计 total =", sum(v["total"] for v in data.values()))
