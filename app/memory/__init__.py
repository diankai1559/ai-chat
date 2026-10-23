"""长期记忆：会话片段 + 常驻画像 + 混合检索。

复用 ai-xiaoshou 里已验证的 bge 嵌入与 BM25 融合思路，
但把“按文件切 512 字块”换成“按天切一段、摘要 200 字”，更适合陪伴场景。
"""

from .build import summarize_segment, update_profile
from .store import MemoryStore, Segment

__all__ = ["MemoryStore", "Segment", "summarize_segment", "update_profile"]
