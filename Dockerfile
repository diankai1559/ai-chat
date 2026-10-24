# 小满 · 长期记忆 AI 陪伴
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    RAG_MODEL_DIR=/opt/models

WORKDIR /app

# libgomp1 是 CPU 版 torch 的运行时依赖；国内直连 deb.debian.org 很慢，先换清华源
RUN (sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true) \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 只装 CPU 版 torch，避免把 CUDA 依赖打进镜像
RUN pip install --retries 10 --timeout 60 torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .

# 默认走国内镜像，海外服务器可用 --build-arg PIP_INDEX=https://pypi.org/simple 覆盖
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --retries 10 --timeout 60 -i "$PIP_INDEX" -r requirements.txt

# 构建期预下载向量模型，运行时不联网
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('BAAI/bge-small-zh-v1.5', cache_folder='/opt/models/hf')"

COPY app ./app
COPY static ./static

RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app /opt/models
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ping', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
