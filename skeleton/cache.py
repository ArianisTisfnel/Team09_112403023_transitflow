"""
TransitFlow — Query Result Cache
=================================
TTL-aware LRU cache for low-volatility query results.

CACHE RULES:
- DO cache: fares and metro schedules (change infrequently)
- DO NOT cache: seat availability and bookings (real-time, oversell risk)
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """Thread-safe LRU cache with per-entry TTL expiry."""

    def __init__(self, max_size: int = 128, ttl_seconds: int = 300) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                self._misses += 1
                return None
            value, expire_at = self._store[key]
            if time.monotonic() > expire_at:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            logger.debug("Cache HIT  key=%s  hits=%d misses=%d", key, self._hits, self._misses)
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, time.monotonic() + self._ttl)
            if len(self._store) > self._max_size:
                evicted, _ = self._store.popitem(last=False)
                logger.debug("Cache EVICT (LRU) key=%s", evicted)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            active = sum(1 for _, (_, exp) in self._store.items() if exp > now)
            return {
                "size": len(self._store),
                "active": active,
                "max_size": self._max_size,
                "ttl_seconds": self._ttl,
                "hits": self._hits,
                "misses": self._misses,
            }


# ── Module-level shared instances ─────────────────────────────────────────────

# Keyed as "fare:{schedule_id}:{fare_class}:{stops_travelled}" — fares rarely change
fare_cache = CacheManager(max_size=512, ttl_seconds=600)

# Keyed as "metro_sched:{origin_id}:{destination_id}" — schedules stable within a day
schedule_cache = CacheManager(max_size=256, ttl_seconds=300)

# Keyed as "policy:{id}" — pre-loaded at startup, long TTL
policy_cache = CacheManager(max_size=100, ttl_seconds=3600)
