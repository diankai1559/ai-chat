"""集中管理项目路径，全部以项目根目录为锚点，避免依赖启动时的工作目录。"""
from pathlib import Path
import os
from dotenv import load_dotenv

# app/config.py -> app/ -> 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"          # 环境变量文件
load_dotenv(ENV_PATH, override=True)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_SECONDS = 7200

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# 生成温度：主模型负责像人一样说话，温度偏高；状态提取器固定 0，在 app/state.py 里写死
CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.8"))

# 公网免费服务防滥用：单用户每天的消息额度（Redis 不可用时放行）
DAILY_MESSAGE_LIMIT = int(os.getenv("DAILY_MESSAGE_LIMIT", "200"))

# 提示词公平性预算（按字符算，不按 token）：
#   固定骨架 400 + 记忆 800 = 1200
#   原版：1 份 800 字摘要；最终版：4 份 × 200 字（画像 1 + 召回 3）
BASE_PROMPT_CHARS = int(os.getenv("BASE_PROMPT_CHARS", "400"))
MEMORY_CHAR_BUDGET = int(os.getenv("MEMORY_CHAR_BUDGET", "800"))
SEGMENT_CHAR_LIMIT = int(os.getenv("SEGMENT_CHAR_LIMIT", "200"))
SEGMENT_COUNT = int(os.getenv("SEGMENT_COUNT", "4"))

DATA_DIR = BASE_DIR / "data"          # SQLite 数据库存放目录
STATIC_DIR = BASE_DIR / "static"      # 前端静态资源
DB_PATH = DATA_DIR / "chat.db"        # SQLite 数据库文件

# ---------- 长期记忆（RAG）----------
RAG_MODEL_DIR = Path(os.getenv("RAG_MODEL_DIR", str(DATA_DIR / "rag" / "models")))
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
SEGMENT_RETRIEVE_TOP_K = int(os.getenv("SEGMENT_RETRIEVE_TOP_K", "3"))