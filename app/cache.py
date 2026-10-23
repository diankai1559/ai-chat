import json
import threading
import time

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from .config import REDIS_HOST, REDIS_PORT

# Redis 只是加速手段，绝不允许拖慢主流程。核心策略：
#   1) 关闭 redis-py 内置重试（redis 8 默认会重试多次，把 0.5s 超时拖成 ~9s）；
#   2) 连接/命令超时都很短；
#   3) 由后台线程负责探活，请求路径只读状态，永不在 Redis 上阻塞。
_CONNECT_TIMEOUT = 0.5  # 秒，连接 Redis 的超时（本地 0.5s 足够）
_SOCKET_TIMEOUT = 0.5   # 秒，单条命令超时
_COOLDOWN = 30.0        # 秒，失败后多久再尝试重连
_PROBE_INTERVAL = 10.0  # 秒，后台探活线程的循环间隔
_RETRY = Retry(NoBackoff(), 0)  # 禁用内置重试，超时完全由我们自己控制

# WSL2 的 Redis 经端口转发暴露：localhost 会同时解析到 ::1 与 127.0.0.1，
# 连接失败时两个地址各超时一次、耗时翻倍，这里统一走 IPv4。
_HOST = "127.0.0.1" if REDIS_HOST == "localhost" else REDIS_HOST

_lock = threading.Lock()
_client = None
_open_until = 0.0  # 熔断器打开到的时刻（time.monotonic()）


def _new_client():
    return redis.Redis(
        host=_HOST, port=REDIS_PORT, db=0, decode_responses=True,
        socket_connect_timeout=_CONNECT_TIMEOUT,
        socket_timeout=_SOCKET_TIMEOUT,
        retry=_RETRY, retry_on_error=[],
    )


def _trip(exc):
    """记录一次失败：丢弃死连接并打开熔断器，冷却期内不再尝试。"""
    global _client, _open_until
    with _lock:
        _client = None
        _open_until = time.monotonic() + _COOLDOWN
    print(f"Redis 不可用，缓存/限流降级运行: {exc}")


def _ensure_client():
    """在后台线程里尝试建立/恢复连接，绝不在请求路径调用。"""
    global _client, _open_until
    with _lock:
        if _client is not None or time.monotonic() < _open_until:
            return
        try:
            client = _new_client()
            client.ping()
        except redis.RedisError as e:
            _open_until = time.monotonic() + _COOLDOWN
            print(f"Redis 不可用，缓存/限流降级运行: {e}")
            return
        _client = client
        _open_until = 0.0


def _check_health():
    """后台探活：没有连接就尝试建立；已有连接就 ping 一下，尽早发现失效。"""
    client = _client
    if client is None:
        _ensure_client()
        return
    try:
        client.ping()
    except redis.RedisError as e:
        _trip(e)


def _health_loop():
    while True:
        _check_health()
        time.sleep(_PROBE_INTERVAL)


def _get_client():
    """只读当前客户端；None 表示降级。请求路径下绝不发起连接。"""
    return _client


def _call(fn, default):
    """执行一条 Redis 命令：任何失败都降级返回 default，绝不上抛。"""
    client = _client
    if client is None:
        return default
    try:
        return fn(client)
    except redis.RedisError as e:
        _trip(e)  # 命令失败同样丢弃连接并熔断，避免每次请求都阻塞
        return default


def get_recent(user_id, ttl=3600):
    """当前会话最近几条消息，登录预热时写入。"""
    data = _call(lambda c: c.get(f"chat:user:{user_id}:recent"), None)
    if not data:
        return None
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None


def set_recent(user_id, messages, ttl=3600):
    _call(lambda c: c.set(
        f"chat:user:{user_id}:recent", json.dumps(messages, ensure_ascii=False), ex=ttl,
    ), None)


def get_memory(user_id, ttl=3600):
    """画像 + 片段摘要 + 向量，预热后整块复用。"""
    data = _call(lambda c: c.get(f"chat:user:{user_id}:memory"), None)
    if not data:
        return None
    try:
        return json.loads(data)
    except (ValueError, TypeError):
        return None


def set_memory(user_id, memory, ttl=3600):
    _call(lambda c: c.set(
        f"chat:user:{user_id}:memory", json.dumps(memory, ensure_ascii=False), ex=ttl,
    ), None)


def invalidate_memory(user_id):
    _call(lambda c: c.delete(f"chat:user:{user_id}:memory"), None)


def check_rate_limit(ip, limit=20, window=60):
    key = f"limit:ip:{ip}:chat"

    def op(client):
        count = client.incr(key)
        if count == 1:
            client.expire(key, window)
        return count <= limit

    return _call(op, True)  # Redis 不可用时放行，避免误伤用户


# 启动后台探活线程：Redis 恢复后自动重新启用，请求路径无需等待
threading.Thread(target=_health_loop, daemon=True, name="redis-health").start()
