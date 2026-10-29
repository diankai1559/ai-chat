"""接口层依赖：请求里反复要用的东西。

- get_current_user  校验 Bearer token 并取出用户
- client_ip         反向代理下取真实 IP，供限流使用
"""

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer

from ..infrastructure import repositories as repo
from ..infrastructure.db import User
from ..infrastructure.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def _unauthorized(detail: str) -> HTTPException:
    """统一 401 的响应头，前端按标准 Bearer 流程处理。"""
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """校验 token 并取出用户；过期、非法、用户已删都返回 401。"""
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token过期")
    except jwt.InvalidTokenError:
        raise _unauthorized("无效的token")

    user_id = payload.get("user_id")
    if user_id is None:
        raise _unauthorized("无效的token")

    user = repo.get_user(user_id)
    if user is None:
        raise _unauthorized("不存在的用户")
    return user


def client_ip(request: Request) -> str:
    """反向代理后取真实 IP；直连时回落到 socket 地址。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
