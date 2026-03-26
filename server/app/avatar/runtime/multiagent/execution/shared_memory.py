"""SharedMemoryNamespace — inter-agent shared state with access control.

Allows subtasks to read/write shared state during execution without
passing everything through upstream_results. Supports:
- Namespace isolation per task session
- Read/write access control per role
- Entry count and value size limits
- Thread-safe operations
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.avatar.runtime.multiagent.config import MultiAgentConfig

logger = logging.getLogger(__name__)


@dataclass
class MemoryEntry:
    """Single shared memory entry."""
    key: str
    value: Any
    writer_role: str
    writer_node_id: str
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class NamespacePolicy:
    """Access control policy for a shared memory namespace."""
    read_roles: frozenset = frozenset()   # empty = all can read
    write_roles: frozenset = frozenset()  # empty = all can write


class SharedMemoryNamespace:
    """Thread-safe shared memory namespace for inter-agent communication.

    Usage:
        mem = SharedMemoryNamespace("session_123", config)
        mem.write("research_data", {"facts": [...]}, role="researcher", node_id="t_0")
        data = mem.read("research_data", role="writer")
    """

    def __init__(
        self,
        namespace_id: str,
        config: Optional[MultiAgentConfig] = None,
        policy: Optional[NamespacePolicy] = None,
    ) -> None:
        self._namespace_id = namespace_id
        self._cfg = config or MultiAgentConfig()
        self._policy = policy or NamespacePolicy()
        self._lock = threading.Lock()
        self._entries: Dict[str, MemoryEntry] = {}

    @property
    def namespace_id(self) -> str:
        return self._namespace_id

    def _check_read(self, role: str) -> bool:
        if not self._policy.read_roles:
            return True
        return role in self._policy.read_roles

    def _check_write(self, role: str) -> bool:
        if not self._policy.write_roles:
            return True
        return role in self._policy.write_roles

    def read(self, key: str, role: str = "") -> Optional[Any]:
        """Read a value from shared memory. Returns None if not found or access denied."""
        if not self._cfg.shared_memory_enabled:
            return None
        if role and not self._check_read(role):
            logger.debug("[SharedMemory] Read denied: role=%s key=%s", role, key)
            return None
        with self._lock:
            entry = self._entries.get(key)
            return entry.value if entry else None

    def write(
        self,
        key: str,
        value: Any,
        role: str = "",
        node_id: str = "",
    ) -> bool:
        """Write a value to shared memory. Returns False if denied or at capacity."""
        if not self._cfg.shared_memory_enabled:
            return False
        if role and not self._check_write(role):
            logger.debug("[SharedMemory] Write denied: role=%s key=%s", role, key)
            return False

        # Value size check
        sv = str(value)
        if len(sv) > self._cfg.shared_memory_max_value_chars:
            logger.warning(
                "[SharedMemory] Value too large: key=%s len=%d max=%d",
                key, len(sv), self._cfg.shared_memory_max_value_chars,
            )
            return False

        with self._lock:
            if key not in self._entries and len(self._entries) >= self._cfg.shared_memory_max_entries:
                logger.warning("[SharedMemory] Namespace %s at capacity (%d)", self._namespace_id, len(self._entries))
                return False
            self._entries[key] = MemoryEntry(
                key=key, value=value,
                writer_role=role, writer_node_id=node_id,
            )
        return True

    def delete(self, key: str, role: str = "") -> bool:
        """Delete an entry. Returns True if found and deleted."""
        if role and not self._check_write(role):
            return False
        with self._lock:
            return self._entries.pop(key, None) is not None

    def list_keys(self, role: str = "") -> List[str]:
        """List all keys visible to the given role."""
        if role and not self._check_read(role):
            return []
        with self._lock:
            return list(self._entries.keys())

    def get_all(self, role: str = "") -> Dict[str, Any]:
        """Get all entries as a dict. Respects read access."""
        if role and not self._check_read(role):
            return {}
        with self._lock:
            return {k: e.value for k, e in self._entries.items()}

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def size(self) -> int:
        with self._lock:
            return len(self._entries)


# ── Namespace registry (per task session) ───────────────────────────

_namespaces: Dict[str, SharedMemoryNamespace] = {}
_ns_lock = threading.Lock()


def get_shared_memory(
    namespace_id: str,
    config: Optional[MultiAgentConfig] = None,
    policy: Optional[NamespacePolicy] = None,
) -> SharedMemoryNamespace:
    """Get or create a shared memory namespace."""
    with _ns_lock:
        if namespace_id not in _namespaces:
            _namespaces[namespace_id] = SharedMemoryNamespace(
                namespace_id, config, policy,
            )
        return _namespaces[namespace_id]


def remove_shared_memory(namespace_id: str) -> bool:
    """Remove a namespace (cleanup after task completion)."""
    with _ns_lock:
        ns = _namespaces.pop(namespace_id, None)
        if ns:
            ns.clear()
            return True
        return False
