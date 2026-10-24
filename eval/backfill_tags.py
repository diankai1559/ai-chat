"""给已有的 100 段对话快照补结构化标签（不改写原摘要）。

每段调用一次低温 JSON 提取，产出 time/place/people/emotion/topic/open_loops/importance，
写进新的快照文件，供带标签的检索评测使用。

用法：python -m eval.backfill_tags
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from app.memory.build import extract_tags

HERE = Path(__file__).resolve().parent
RESULT_DIR = HERE / "results"


def main() -> None:
    api_key = os.getenv("EVAL_API_KEY")
    if not api_key:
        sys.exit("缺少 EVAL_API_KEY")

    candidates = [
        p for p in glob.glob(str(RESULT_DIR / "RAG最终版_对话记录_100段_*.json"))
        if "_标签版_" not in p
    ]
    if not candidates:
        sys.exit("没有找到 100 段快照")
    source = Path(max(candidates, key=os.path.getmtime))
    snap = json.loads(source.read_text(encoding="utf-8"))

    groups: dict[int, list[dict]] = {}
    for row in snap["transcript"]:
        turns = groups.setdefault(int(row["scene"]), [])
        turns.append({"role": "user", "content": row["user"]})
        turns.append({"role": "assistant", "content": row["assistant"]})

    segments = snap["memory"]["segments"]
    print(f"基于 {source.name} 给 {len(segments)} 段补标签", flush=True)

    for index, segment in enumerate(segments, start=1):
        tags = extract_tags(groups.get(index, []), api_key=api_key)
        segment["tags"] = tags
        if index % 10 == 0:
            print(f"  {index}/{len(segments)}", flush=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULT_DIR / f"RAG最终版_对话记录_100段_标签版_{stamp}.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：{out}", flush=True)


if __name__ == "__main__":
    main()
