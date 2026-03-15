"""
Developer SDK — abstract base classes for extending the agent runtime.

Status: experimental
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# BaseVerifier
# ---------------------------------------------------------------------------

class BaseVerifier(ABC):
    """
    Abstract base class for custom verifiers.

    Implement verify() to add custom verification logic.
    Exceptions are isolated by CompletionGate — they return UNCERTAIN, not crash.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique verifier name (used for deduplication and logging)."""
        ...

    @abstractmethod
    async def verify(
        self,
        target: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Verify a target.

        Returns dict with:
          - status: "passed" | "failed" | "uncertain"
          - message: human-readable result description
          - details: optional dict with additional info
        """
        ...


# ---------------------------------------------------------------------------
# DomainPack (SDK version — extends the dataclass)
# ---------------------------------------------------------------------------

class BaseDomainPack(ABC):
    """
    Abstract base class for custom domain packs.
    Implement get_pack() to return a DomainPack dataclass instance.
    """

    @abstractmethod
    def get_pack(self) -> Any:
        """Return a DomainPack dataclass instance."""
        ...


# ---------------------------------------------------------------------------
# PolicyRule (SDK version)
# ---------------------------------------------------------------------------

class BasePolicyRule(ABC):
    """
    Abstract base class for custom policy rules.
    Implement evaluate() to add custom policy logic.
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique rule identifier."""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """Rule priority (higher = evaluated first)."""
        ...

    @abstractmethod
    def evaluate(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Evaluate the rule.

        Returns: "allow" | "require_approval" | "deny"
        """
        ...
