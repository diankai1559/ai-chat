import bcrypt
import jwt
import time
from app.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRES_SECONDS

def hash_password(password: str) -> str:
    """使用 bcrypt 直接哈希密码。"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """验证密码。"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(user_id: int) -> str:
    payload = {"user_id": user_id,
               "exp": int(time.time()) + JWT_EXPIRES_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
