"""Redis connection manager for cache persistence.

Provides a singleton Redis client that connects to the dedicated
xiaozhi-esp32-server-redis container via Docker Compose networking.
"""

import json
import time
import logging
from typing import Any, Optional

REDIS_HOST = "xiaozhi-esp32-server-redis"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_SOCKET_TIMEOUT = 3.0


class RedisClient:
    """Thin wrapper around a shared redis.Redis connection pool."""

    def __init__(self):
        self._client = None
        self._logger = logging.getLogger("redis_client")

    def _connect(self):
        if self._client is not None:
            try:
                self._client.ping()
                return
            except Exception:
                self._client = None

        try:
            import redis

            pool = redis.ConnectionPool(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                socket_connect_timeout=REDIS_SOCKET_TIMEOUT,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                decode_responses=True,
            )
            self._client = redis.Redis(connection_pool=pool)
            self._client.ping()
            self._logger.info("Redis connected at %s:%s", REDIS_HOST, REDIS_PORT)
        except Exception as exc:
            self._logger.warning("Redis unavailable: %s — cache degraded", exc)
            self._client = None

    @property
    def available(self) -> bool:
        self._connect()
        return self._client is not None

    def get(self, key: str) -> Optional[Any]:
        if not self.available:
            return None
        try:
            raw = self._client.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        if not self.available:
            return False
        try:
            raw = json.dumps(value, ensure_ascii=False)
            if ttl is not None and ttl > 0:
                self._client.setex(key, int(ttl), raw)
            else:
                self._client.set(key, raw)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> bool:
        if not self.available:
            return False
        try:
            return bool(self._client.delete(key))
        except Exception:
            return False

    def exists(self, key: str) -> bool:
        if not self.available:
            return False
        try:
            return bool(self._client.exists(key))
        except Exception:
            return False

    def keys(self, pattern: str) -> list:
        if not self.available:
            return []
        try:
            return list(self._client.keys(pattern))
        except Exception:
            return []

    def close(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


# Module-level singleton
redis_client = RedisClient()
