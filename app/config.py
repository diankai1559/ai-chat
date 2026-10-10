"""集中管理项目路径，全部以项目根目录为锚点，避免依赖启动时的工作目录。"""
from pathlib import Path

# app/config.py -> app/ -> 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"          # SQLite 数据库存放目录
STATIC_DIR = BASE_DIR / "static"      # 前端静态资源
ENV_PATH = BASE_DIR / ".env"          # 环境变量文件
DB_PATH = DATA_DIR / "chat.db"        # SQLite 数据库文件