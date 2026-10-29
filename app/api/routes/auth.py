"""认证路由：注册、登录、校验用户自备的 API Key。

路由只做三件事：读请求、按顺序调用下层、把结果翻译成 HTTP 响应。
真正的校验规则在 infrastructure/security.py，数据读写在 repositories.py。
"""

import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.exc import IntegrityError

from ..deps import client_ip, get_current_user
from ..schemas import (
    ApiKeyTestResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from ...application.chat_service import warm_up
from ...infrastructure import repositories as repo
from ...infrastructure.cache import check_rate_limit
from ...infrastructure.db import User
from ...infrastructure.llm import test_api_key
from ...infrastructure.security import create_access_token, hash_password, verify_password

router = APIRouter()


@router.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest, request: Request):
    """注册新账号；同一 IP 每小时最多 10 次，避免被批量刷。"""
    if not check_rate_limit(f"register:{client_ip(request)}", limit=10, window=3600):
        raise HTTPException(status_code=429, detail="注册太频繁，请稍后再试")

    if repo.find_user_by_name(req.username) is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")

    try:
        user = repo.create_user(req.username, hash_password(req.password))
    except IntegrityError:
        # 两次请求同时注册同一个名字时，唯一约束会在这里兜住
        raise HTTPException(status_code=400, detail="用户名已存在")

    return RegisterResponse(id=user.id, username=user.username)


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request):
    """登录并签发 token；成功后后台预热本用户的记忆缓存。"""
    if not check_rate_limit(f"login:{client_ip(request)}", limit=30, window=60):
        raise HTTPException(status_code=429, detail="登录尝试太频繁，请稍后再试")

    user = repo.find_user_by_name(req.username)
    # 用户不存在与密码错误返回同一句，避免暴露账号是否存在
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id)
    threading.Thread(target=warm_up, args=(user.id,), daemon=True).start()

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        username=user.username,
    )


@router.post("/api-key/test", response_model=ApiKeyTestResponse)
def test_api_key_endpoint(
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    user: User = Depends(get_current_user),
):
    """用传入的 API Key 打一个极小请求，校验 Key 是否可用。"""
    ok, message = test_api_key(api_key)
    return ApiKeyTestResponse(ok=ok, message=message)
