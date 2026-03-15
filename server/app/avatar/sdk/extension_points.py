"""
Developer SDK — extension point registration interfaces.

Status: experimental

Usage:
    from app.avatar.sdk import register_verifier, register_domain_pack

    @register_verifier
    class MyVerifier(BaseVerifier):
        ...
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional, Type

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global registries (in-memory, populated at import time)
# ---------------------------------------------------------------------------

_registered_verifiers: List[Any] = []
_registered_artifact_types: List[str] = []
_registered_domain_packs: List[Any] = []
_registered_policy_rules: List[Any] = []
_registered_skills: List[Any] = []


def register_verifier(cls: Type) -> Type:
    """
    Decorator to register a custom verifier class.
    The verifier will be loaded into VerifierRegistry at runtime startup.
    """
    _registered_verifiers.append(cls)
    logger.debug(f"[SDK] Registered verifier: {cls.__name__}")
    return cls


def register_artifact_type(type_name: str) -> Callable:
    """
    Decorator factory to register a custom artifact type name.
    """
    def decorator(cls: Type) -> Type:
        _registered_artifact_types.append(type_name)
        logger.debug(f"[SDK] Registered artifact type: {type_name}")
        return cls
    return decorator


def register_domain_pack(pack_or_cls: Any) -> Any:
    """
    Register a DomainPack instance or BaseDomainPack subclass.
    """
    _registered_domain_packs.append(pack_or_cls)
    name = getattr(pack_or_cls, "pack_id", None) or getattr(pack_or_cls, "__name__", str(pack_or_cls))
    logger.debug(f"[SDK] Registered domain pack: {name}")
    return pack_or_cls


def register_policy_rule(rule_or_cls: Any) -> Any:
    """
    Register a custom PolicyRule instance or BasePolicyRule subclass.
    """
    _registered_policy_rules.append(rule_or_cls)
    name = getattr(rule_or_cls, "rule_id", None) or getattr(rule_or_cls, "__name__", str(rule_or_cls))
    logger.debug(f"[SDK] Registered policy rule: {name}")
    return rule_or_cls


def register_skill(skill_or_cls: Any) -> Any:
    """
    Register a custom skill implementation.
    """
    _registered_skills.append(skill_or_cls)
    name = getattr(skill_or_cls, "name", None) or getattr(skill_or_cls, "__name__", str(skill_or_cls))
    logger.debug(f"[SDK] Registered skill: {name}")
    return skill_or_cls


# ---------------------------------------------------------------------------
# Accessors (used by runtime bootstrap)
# ---------------------------------------------------------------------------

def get_registered_verifiers() -> List[Any]:
    return list(_registered_verifiers)


def get_registered_domain_packs() -> List[Any]:
    return list(_registered_domain_packs)


def get_registered_policy_rules() -> List[Any]:
    return list(_registered_policy_rules)


def get_registered_skills() -> List[Any]:
    return list(_registered_skills)
