"""本地向量化：bge-small-zh-v1.5，懒加载；加载失败时检索降级为纯 BM25。"""

from __future__ import annotations

import os
import threading

from ..config import EMBEDDING_MODEL, RAG_MODEL_DIR

# 国内直连 huggingface 不稳定，默认走镜像
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

_CACHE_DIR = RAG_MODEL_DIR / "hf"
_lock = threading.Lock()
_model = None
_failed = False


def get_model():
    """首次调用才加载，多线程下只加载一次。"""
    global _model, _failed
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        if _failed:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(_CACHE_DIR))
        except Exception as exc:
            _failed = True
            print(f"Embedding 模型加载失败（检索降级为 BM25）: {exc}")
            return None
        print("Embedding 模型加载完成")
        return _model


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """批量向量化，已做 L2 归一化，点积即余弦相似度。"""
    if not texts:
        return None
    model = get_model()
    if model is None:
        return None
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def warm_up() -> None:
    get_model()


threading.Thread(target=warm_up, daemon=True, name="embedding-warmup").start()
