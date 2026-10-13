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

DATA_DIR = BASE_DIR / "data"          # SQLite 数据库存放目录
STATIC_DIR = BASE_DIR / "static"      # 前端静态资源
DB_PATH = DATA_DIR / "chat.db"        # SQLite 数据库文件