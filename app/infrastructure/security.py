"""密码哈希与 JWT：只做加解密，不关心 HTTP。

调用方：api/deps.py（校验 token）、api/routes/auth.py（签发 token、哈希密码）。
接口层的 401 文案与响应头不写在本文，避免基础设施层反过来依赖框架。
"""

import time

import bcrypt
import jwt

from ..config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRES_SECONDS


def hash_password(password: str) -> str:
    """使用 bcrypt 直接哈希密码。"""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """验证密码。"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_access_token(user_id: int) -> str:
    """签发 access token，载荷只放 user_id 与过期时间。"""
    payload = {
        "user_id": user_id,
        "exp": int(time.time()) + JWT_EXPIRES_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析 token 载荷；过期或非法时抛 jwt 自己的异常，由接口层决定怎么响应。"""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
