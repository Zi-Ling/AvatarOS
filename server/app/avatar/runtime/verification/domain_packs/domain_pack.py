"""
DomainPack dataclass — bundles verifiers, artifact types, repair policy and prompt hints
for a specific execution scenario.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class DomainPack:
    """
    A scenario domain pack that bundles:
    - prompt_hint: injected before available_skills in PlannerPromptBuilder
    - verifier_pack: dict of {verifier_name: verifier_instance}
    - artifact_types: list of expected ArtifactType values
    - repair_policy: optional RepairPolicy override
    - supported_goal_types: glob/keyword patterns for GoalNormalizer matching
    """
    pack_id: str
    name: str
    description: str
    prompt_hint: str
    verifier_pack: Dict[str, Any] = field(default_factory=dict)
    artifact_types: List[str] = field(default_factory=list)
    repair_policy: Optional[Any] = None          # RepairPolicy instance or None
    supported_goal_types: List[str] = field(default_factory=list)
