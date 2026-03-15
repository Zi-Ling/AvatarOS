"""
Agent Runtime Developer SDK — experimental extension interfaces.

WARNING: This SDK is experimental. APIs may change without notice.

Usage:
    from app.avatar.sdk import (
        BaseVerifier,
        BaseDomainPack,
        BasePolicyRule,
        register_verifier,
        register_domain_pack,
        register_policy_rule,
        register_skill,
    )
"""
# Mark as experimental
__experimental__ = True

from app.avatar.sdk.base_classes import BaseVerifier, BaseDomainPack, BasePolicyRule
from app.avatar.sdk.extension_points import (
    register_verifier,
    register_artifact_type,
    register_domain_pack,
    register_policy_rule,
    register_skill,
    get_registered_verifiers,
    get_registered_domain_packs,
    get_registered_policy_rules,
    get_registered_skills,
)

__all__ = [
    # Base classes
    "BaseVerifier",
    "BaseDomainPack",
    "BasePolicyRule",
    # Registration decorators
    "register_verifier",
    "register_artifact_type",
    "register_domain_pack",
    "register_policy_rule",
    "register_skill",
    # Accessors
    "get_registered_verifiers",
    "get_registered_domain_packs",
    "get_registered_policy_rules",
    "get_registered_skills",
]
