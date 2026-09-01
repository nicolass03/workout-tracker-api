from __future__ import annotations

import logging
from hashlib import sha256

from api.config import Settings

logger = logging.getLogger(__name__)


class ResponseCache:
    """Optional Redis cache. Every operation fails open to PostgreSQL."""

    def __init__(self) -> None:
        self._redis = None

    async def start(self, settings: Settings) -> None:
        if not settings.redis_url:
            return
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(
                settings.redis_url,
                encoding=None,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
                health_check_interval=30,
            )
            await self._redis.ping()
        except Exception:
            logger.warning("Redis unavailable; response caching disabled", exc_info=True)
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def generation(self, user_id: str) -> int | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"move:{user_id}:generation")
            return int(raw or 0)
        except Exception:
            logger.warning("Redis generation read failed", exc_info=True)
            return None

    async def invalidate_user(self, user_id: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.incr(f"move:{user_id}:generation")
        except Exception:
            logger.warning("Redis invalidation failed", exc_info=True)

    async def get(self, key: str) -> bytes | None:
        if self._redis is None:
            return None
        try:
            return await self._redis.get(key)
        except Exception:
            logger.warning("Redis cache read failed", exc_info=True)
            return None

    async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
        if self._redis is None:
            return
        try:
            jitter = int.from_bytes(sha256(key.encode()).digest()[:2], "big") % max(
                ttl_seconds // 10, 1
            )
            await self._redis.set(key, payload, ex=ttl_seconds + jitter)
        except Exception:
            logger.warning("Redis cache write failed", exc_info=True)


response_cache = ResponseCache()
