import json
import time
import redis
from .config import REDIS_HOST, REDIS_PORT

_client = None
_last_fail = 0.0
_RETRY_INTERVAL = 30.0  # Redis 不可用后，至少间隔这么久才重试连接


def _get_client():
    """惰性创建 Redis 客户端并探测可用性。

    Redis 不可用时返回 None，调用方据此降级（跳过缓存/放行请求），
    应用仍可正常启动运行，而不会在导入模块时因连接失败而中断。
    """
    global _client, _last_fail
    if _client is not None:
        return _client
    # 刚探测失败过，短时间内不再重试，避免每次请求都阻塞在连接上
    if time.monotonic() - _last_fail < _RETRY_INTERVAL:
        return None
    try:
        client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True,
            socket_connect_timeout=2, socket_timeout=2,
        )
        client.ping()
        _client = client
        return _client
    except redis.RedisError as e:
        _last_fail = time.monotonic()
        print(f"Redis 不可用，缓存/限流降级运行: {e}")
        return None


def get_messages(session_uuid: str) -> list | None:
    client = _get_client()
    if client is None:
        return None
    try:
        data = client.get(f"chat:session:{session_uuid}:messages")
        return json.loads(data) if data else None
    except redis.RedisError as e:
        print(f"Error retrieving messages: {e}")
        return None


def set_messages(session_uuid: str, message: list, ttl: int = 3600) -> None:
    client = _get_client()
    if client is None:
        return
    try:
        client.set(f"chat:session:{session_uuid}:messages", json.dumps(message), ex=ttl)
    except redis.RedisError as e:
        print(f"Error setting messages: {e}")


def invalidate_messages(session_uuid: str):
    client = _get_client()
    if client is None:
        return
    try:
        client.delete(f"chat:session:{session_uuid}:messages")
    except redis.RedisError as e:
        print(f"Error invalidating messages: {e}")


def check_rate_limit(ip: str, limit: int = 20, window: int = 60) -> bool:
    client = _get_client()
    if client is None:
        return True  # Redis 不可用时放行，避免误伤用户
    key = f"limit:ip:{ip}:chat"
    try:
        count = client.incr(key)
        if count == 1:
            client.expire(key, window)
        return count <= limit
    except redis.RedisError as e:
        print(f"Error checking rate limit: {e}")
        return True