"""Shared multi-worker rate limiter.

Production requires Redis. Development may explicitly use a local fallback.
"""
import os
import time
from collections import defaultdict, deque

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

_LOCAL = defaultdict(deque)
_REDIS = None


def _redis_client():
    global _REDIS
    if _REDIS is not None:
        return _REDIS
    url = os.environ.get("AI_GATEWAY_REDIS_URL")
    if not url or redis is None:
        return None
    _REDIS = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1)
    return _REDIS


def _production():
    return os.environ.get("AI_GATEWAY_ENV", "development") == "production"


def allow(key, limit, window=60, prefix="ai:rl", consume=True):
    key = str(key or "anonymous")
    r = _redis_client()
    if r is not None:
        bucket = f"{prefix}:{key}"
        now = time.time()
        pipe = r.pipeline()
        pipe.zremrangebyscore(bucket, 0, now - window)
        pipe.zcard(bucket)
        if consume:
            pipe.zadd(bucket, {f"{now}:{os.getpid()}:{time.time_ns()}": now})
            pipe.expire(bucket, window + 5)
        _, count, *_ = pipe.execute()
        return int(count) < int(limit)

    if _production():
        return False
    if os.environ.get("AI_GATEWAY_ALLOW_LOCAL_LIMITER", "0") != "1":
        return False
    now = time.time()
    q = _LOCAL[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        return False
    if consume:
        q.append(now)
    return True


def check(key, limit, window=60, prefix="ai:rl"):
    return allow(key, limit, window=window, prefix=prefix, consume=True)


def blocked(key, limit, window=60, prefix="ai:rl"):
    return not allow(key, limit, window=window, prefix=prefix, consume=False)
