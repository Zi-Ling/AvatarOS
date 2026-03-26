"""SubtaskResultCache — cache subtask results to avoid redundant execution.

Uses content-based hashing (role + description + input_bindings) as cache key.
TTL-based expiration. Thread-safe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.avatar.runtime.multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cached subtask result."""
    key: str
    result_data: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    ttl: float = 3600.0
    hit_count: int = 0

    @property
    def expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


class SubtaskResultCache:
    """In-memory LRU cache for subtask execution results.

    Cache key = hash(role + description + sorted input_bindings).
    Thread-safe via lock.
    """

    def __init__(self, config: Optional[MultiAgentConfig] = None) -> None:
        self._cfg = config or MultiAgentConfig()
        self._lock = threading.Lock()
        self._cache: Dict[str, CacheEntry] = {}
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    @staticmethod
    def _make_key(role: str, description: str, input_bindings: Dict[str, str]) -> str:
        """Generate a deterministic cache key from subtask parameters."""
        raw = json.dumps({
            "role": role,
            "description": description,
            "bindings": sorted(input_bindings.items()),
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    def get(
        self,
        role: str,
        description: str,
        input_bindings: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Look up cached result. Returns None on miss or expiry."""
        if not self._cfg.result_cache_enabled:
            return None

        key = self._make_key(role, description, input_bindings or {})
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._stats["misses"] += 1
                return None
            if entry.expired:
                del self._cache[key]
                self._stats["misses"] += 1
                self._stats["evictions"] += 1
                return None
            entry.hit_count += 1
            self._stats["hits"] += 1
            logger.debug("[ResultCache] HIT key=%s role=%s hits=%d", key, role, entry.hit_count)
            return entry.result_data

    def put(
        self,
        role: str,
        description: str,
        input_bindings: Optional[Dict[str, str]] = None,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store a subtask result in cache."""
        if not self._cfg.result_cache_enabled or result_data is None:
            return

        key = self._make_key(role, description, input_bindings or {})
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self._cfg.result_cache_max_entries:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
                del self._cache[oldest_key]
                self._stats["evictions"] += 1

            self._cache[key] = CacheEntry(
                key=key,
                result_data=result_data,
                ttl=self._cfg.result_cache_ttl_seconds,
            )

    def invalidate(self, role: str, description: str, input_bindings: Optional[Dict[str, str]] = None) -> bool:
        """Remove a specific entry. Returns True if found."""
        key = self._make_key(role, description, input_bindings or {})
        with self._lock:
            return self._cache.pop(key, None) is not None

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            return {
                **self._stats,
                "size": len(self._cache),
                "hit_rate": round(self._stats["hits"] / total, 3) if total > 0 else 0.0,
            }
