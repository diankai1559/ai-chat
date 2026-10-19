import bcrypt
import jwt
import time
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select

from .config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRES_SECONDS
from .db import SessionLocal, User


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


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

def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    try:
        with SessionLocal() as db:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("user_id")
            if user_id is None:
                raise HTTPException(status_code=401, detail="无效的token",headers={"WWW-Authenticate": "Bearer"})
            user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
            if user is None:
                raise HTTPException(status_code=401, detail="不存在的用户",headers={"WWW-Authenticate": "Bearer"})
            return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token过期",headers={"WWW-Authenticate": "Bearer"})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的token",headers={"WWW-Authenticate": "Bearer"})

