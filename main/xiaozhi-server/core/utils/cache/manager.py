"""
Global cache manager with in-memory (L1) and Redis (L2) backends.

Architecture:
  L1 — in-memory OrderedDict (sub-µs, survives short Redis blips)
  L2 — Redis (persistent across restarts, shared across instances)

On read:
  1. L1 hit → return immediately
  2. L1 miss → try L2 (Redis)
  3. L2 hit → promote to L1 → return
  4. Both miss → return None

On write:
  Write to L1 synchronously, then L2.
  L2 failure is non-fatal — next restart may need to warm again.

TTL behaviour:
  L1 honours TTL via CacheEntry expiry.
  L2 (Redis) uses native EXPIRE/PEXPIRE so expired keys are
  reclaimed automatically without periodic cleanup.
"""

import time
import json
import threading
from typing import Any, Optional, Dict
from collections import OrderedDict

from .strategies import CacheStrategy, CacheEntry
from .config import CacheConfig, CacheType
from .redis_client import redis_client


class GlobalCacheManager:
    """Global cache manager with L1 (in-memory) + L2 (Redis) backends."""

    def __init__(self):
        self._logger = None
        self._caches: Dict[str, Dict[str, CacheEntry]] = {}
        self._configs: Dict[str, CacheConfig] = {}
        self._locks: Dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()
        self._last_cleanup = time.time()
        self._stats = {"hits": 0, "misses": 0, "redis_hits": 0, "evictions": 0, "cleanups": 0}
        # Nanosecond threshold: skip Redis for extremely short TTLs
        self._redis_min_ttl = 30  # seconds

    @property
    def logger(self):
        if self._logger is None:
            from config.logger import setup_logging
            self._logger = setup_logging()
        return self._logger

    # ── key helpers ──────────────────────────────────────────────────

    @staticmethod
    def _redis_key(cache_name: str, key: str) -> str:
        return f"cache:{cache_name}:{key}"

    @staticmethod
    def _cache_name(cache_type: CacheType, namespace: str = "") -> str:
        return f"{cache_type.value}:{namespace}" if namespace else cache_type.value

    # ── L1 cache management ──────────────────────────────────────────

    def _get_or_create_cache(self, cache_name: str, config: CacheConfig) -> Dict[str, CacheEntry]:
        with self._global_lock:
            if cache_name not in self._caches:
                self._caches[cache_name] = (
                    OrderedDict() if config.strategy in (CacheStrategy.LRU, CacheStrategy.TTL_LRU)
                    else {}
                )
                self._configs[cache_name] = config
                self._locks[cache_name] = threading.RLock()
            return self._caches[cache_name]

    def _set_l1(self, cache_name: str, key: str, entry: CacheEntry, config: CacheConfig):
        cache = self._get_or_create_cache(cache_name, config)
        with self._locks[cache_name]:
            if config.strategy in (CacheStrategy.LRU, CacheStrategy.TTL_LRU):
                if key in cache:
                    del cache[key]
                cache[key] = entry
                if config.max_size and len(cache) > config.max_size:
                    oldest = next(iter(cache))
                    del cache[oldest]
                    self._stats["evictions"] += 1
            else:
                cache[key] = entry
                if config.max_size and len(cache) > config.max_size:
                    victim = next(iter(cache))
                    del cache[victim]
                    self._stats["evictions"] += 1

    def _get_l1(self, cache_name: str, key: str, config: CacheConfig) -> Optional[Any]:
        cache = self._caches.get(cache_name)
        if not cache:
            return None
        with self._locks[cache_name]:
            entry = cache.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del cache[key]
                return None
            entry.touch()
            if config.strategy in (CacheStrategy.LRU, CacheStrategy.TTL_LRU):
                del cache[key]
                cache[key] = entry
            return entry.value

    # ── public API ───────────────────────────────────────────────────

    def set(self, cache_type: CacheType, key: str, value: Any,
            ttl: Optional[float] = None, namespace: str = "") -> None:
        cache_name = self._cache_name(cache_type, namespace)
        config = self._configs.get(cache_name) or CacheConfig.for_type(cache_type)
        effective_ttl = ttl if ttl is not None else config.ttl

        entry = CacheEntry(value=value, timestamp=time.time(), ttl=effective_ttl)
        self._set_l1(cache_name, key, entry, config)

        # Write through to Redis if TTL is meaningful
        if effective_ttl is None or effective_ttl >= self._redis_min_ttl:
            rk = self._redis_key(cache_name, key)
            redis_client.set(rk, value, ttl=effective_ttl)

        self._maybe_cleanup(cache_name)

    def get(self, cache_type: CacheType, key: str, namespace: str = "") -> Optional[Any]:
        cache_name = self._cache_name(cache_type, namespace)

        # 1. L1 hit
        config = self._configs.get(cache_name) or CacheConfig.for_type(cache_type)
        val = self._get_l1(cache_name, key, config)
        if val is not None:
            self._stats["hits"] += 1
            return val

        # 2. L2 (Redis) hit → promote to L1
        rk = self._redis_key(cache_name, key)
        redis_val = redis_client.get(rk)
        if redis_val is not None:
            self._stats["redis_hits"] += 1
            # Re-promote to L1 using the cached config's TTL
            cfg = self._configs.get(cache_name) or CacheConfig.for_type(cache_type)
            entry = CacheEntry(value=redis_val, timestamp=time.time(), ttl=cfg.ttl)
            self._set_l1(cache_name, key, entry, cfg)
            return redis_val

        self._stats["misses"] += 1
        return None

    def delete(self, cache_type: CacheType, key: str, namespace: str = "") -> bool:
        cache_name = self._cache_name(cache_type, namespace)
        removed = False
        # Remove from L1
        cache = self._caches.get(cache_name)
        if cache:
            with self._locks.get(cache_name, threading.RLock()):
                if key in cache:
                    del cache[key]
                    removed = True
        # Remove from L2
        rk = self._redis_key(cache_name, key)
        redis_client.delete(rk)
        return removed

    def clear(self, cache_type: CacheType, namespace: str = "") -> None:
        cache_name = self._cache_name(cache_type, namespace)
        cache = self._caches.get(cache_name)
        if cache:
            with self._locks.get(cache_name, threading.RLock()):
                cache.clear()
        # Remove from Redis
        pattern = f"cache:{cache_name}:*"
        for rk in redis_client.keys(pattern):
            redis_client.delete(rk)

    def invalidate_pattern(self, cache_type: CacheType, pattern: str, namespace: str = "") -> int:
        cache_name = self._cache_name(cache_type, namespace)
        count = 0
        cache = self._caches.get(cache_name)
        if cache:
            with self._locks.get(cache_name, threading.RLock()):
                keys = [k for k in cache if pattern in k]
                for k in keys:
                    del cache[k]
                    count += 1
        # Remove from Redis
        rk_pattern = f"cache:{cache_name}:*{pattern}*"
        for rk in redis_client.keys(rk_pattern):
            redis_client.delete(rk)
            count += 1
        return count

    def _maybe_cleanup(self, cache_name: str):
        now = time.time()
        if now - self._last_cleanup > 60:
            self._last_cleanup = now
            cache = self._caches.get(cache_name)
            if not cache:
                return
            with self._locks.get(cache_name, threading.RLock()):
                expired = [k for k, e in cache.items() if e.is_expired()]
                for k in expired:
                    del cache[k]
                if expired:
                    self._stats["cleanups"] += 1

    @property
    def stats(self) -> dict:
        return dict(self._stats)


cache_manager = GlobalCacheManager()
