"""
PlannerGuard - Safety Validation for Graph Patches

Validates LLM-generated GraphPatches before application to ensure:
- Capability-level policy enforcement (allow, deny, require_approval)
- Workspace isolation for file operations
- Resource limit validation
- Cycle detection

Requirements: 31.1-31.14
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.graph_patch import GraphPatch
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.services.approval_service import ApprovalService

logger = logging.getLogger(__name__)


# ==========================================
# Policy Models
# ==========================================

class PolicyAction(str, Enum):
    """Policy enforcement action."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class CapabilityPolicy:
    """Policy for a specific capability."""
    capability_name: str
    action: PolicyAction
    reason: Optional[str] = None


@dataclass
class GuardConfig:
    """PlannerGuard configuration."""
    # Resource limits (Requirement 31.10, 31.11)
    max_nodes_per_patch: int = 20
    max_edges_per_patch: int = 50
    max_total_nodes: int = 200
    max_total_edges: int = 1000

    # Workspace isolation (Requirement 31.8, 31.9)
    workspace_root: Optional[str] = None
    enforce_workspace_isolation: bool = True

    # Capability policies (Requirement 31.5, 31.6)
    capability_policies: List[CapabilityPolicy] = field(default_factory=list)

    # Default policy for unlisted capabilities
    default_policy: PolicyAction = PolicyAction.ALLOW


# ==========================================
# Validation Result
# ==========================================

@dataclass
class ValidationResult:
    """Result of PlannerGuard validation."""
    approved: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_approval: List[str] = field(default_factory=list)

    @property
    def has_violations(self) -> bool:
        return len(self.violations) > 0

    def add_violation(self, msg: str) -> None:
        self.violations.append(msg)
        self.approved = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def add_approval_required(self, capability: str) -> None:
        self.requires_approval.append(capability)


# ==========================================
# PlannerGuard
# ==========================================

class PlannerGuard:
    """
    Validates GraphPatches before application.

    Enforces:
    - Capability-level policies (allow/deny/require_approval)
    - Workspace isolation for file operations
    - Resource limits (nodes/edges per patch, total)
    - Cycle detection after patch application

    Requirements: 31.1-31.14
    """

    def __init__(
        self,
        config: Optional[GuardConfig] = None,
        approval_manager: Optional['ApprovalService'] = None
    ):
        self.config = config or GuardConfig()
        self.approval_manager = approval_manager

        # Build policy lookup map
        self._policy_map: Dict[str, CapabilityPolicy] = {
            p.capability_name: p for p in self.config.capability_policies
        }

        logger.info(
            f"[PlannerGuard] Initialized with {len(self._policy_map)} capability policies, "
            f"workspace_root={self.config.workspace_root}"
        )

    async def validate(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Validate a GraphPatch before application.

        Checks (in order):
        1. Resource limits (nodes/edges per patch)
        2. Total graph size limits after patch
        3. Capability policies (deny → reject, require_approval → ask)
        4. Workspace isolation for file operations
        5. Cycle detection

        Args:
            patch: GraphPatch to validate
            graph: Current ExecutionGraph
            context: Optional execution context (session_id, goal, etc.)

        Returns:
            ValidationResult with approved status and any violations/warnings

        Requirements: 31.1, 31.2, 31.3, 31.4
        """
        result = ValidationResult(approved=True)
        context = context or {}

        # 1. Resource limit validation (Requirement 31.10, 31.11)
        self._check_resource_limits(patch, graph, result)
        if not result.approved:
            return result

        # 2. Capability policy enforcement (Requirement 31.5, 31.6, 31.7)
        await self._check_capability_policies(patch, graph, context, result)
        if not result.approved:
            return result

        # 3. Workspace isolation (Requirement 31.8, 31.9)
        if self.config.enforce_workspace_isolation:
            self._check_workspace_isolation(patch, result, context=context)
            if not result.approved:
                return result

        # 4. Cycle detection (Requirement 31.12, 31.13)
        self._check_cycles(patch, graph, result)

        if result.approved:
            logger.info(
                f"[PlannerGuard] Patch approved: "
                f"{len(patch.actions)} actions, warnings={len(result.warnings)}"
            )
        else:
            logger.warning(
                f"[PlannerGuard] Patch rejected: {result.violations}"
            )

        return result

    def _check_resource_limits(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
        result: ValidationResult
    ) -> None:
        """Check resource limits for the patch. Requirements: 31.10, 31.11"""
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation

        add_nodes = sum(1 for a in patch.actions if a.operation == PatchOperation.ADD_NODE)
        add_edges = sum(1 for a in patch.actions if a.operation == PatchOperation.ADD_EDGE)

        # Per-patch limits
        if add_nodes > self.config.max_nodes_per_patch:
            result.add_violation(
                f"Patch adds {add_nodes} nodes, exceeds limit {self.config.max_nodes_per_patch}"
            )

        if add_edges > self.config.max_edges_per_patch:
            result.add_violation(
                f"Patch adds {add_edges} edges, exceeds limit {self.config.max_edges_per_patch}"
            )

        # Total graph size limits
        total_nodes_after = len(graph.nodes) + add_nodes
        total_edges_after = len(graph.edges) + add_edges

        if total_nodes_after > self.config.max_total_nodes:
            result.add_violation(
                f"Graph would have {total_nodes_after} nodes, exceeds limit {self.config.max_total_nodes}"
            )

        if total_edges_after > self.config.max_total_edges:
            result.add_violation(
                f"Graph would have {total_edges_after} edges, exceeds limit {self.config.max_total_edges}"
            )

    async def _check_capability_policies(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
        context: Dict[str, Any],
        result: ValidationResult
    ) -> None:
        """Check capability-level policies. Requirements: 31.5, 31.6, 31.7"""
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation

        for action in patch.actions:
            if action.operation != PatchOperation.ADD_NODE or action.node is None:
                continue

            capability_name = action.node.capability_name
            policy = self._policy_map.get(capability_name)

            if policy is None:
                # Use default policy
                if self.config.default_policy == PolicyAction.DENY:
                    result.add_violation(
                        f"Capability '{capability_name}' not in allowlist (default policy: deny)"
                    )
                continue

            if policy.action == PolicyAction.DENY:
                reason = policy.reason or f"Capability '{capability_name}' is denied by policy"
                result.add_violation(reason)

            elif policy.action == PolicyAction.REQUIRE_APPROVAL:
                # Request approval via ApprovalService (persistent, REST-accessible)
                if self.approval_manager:
                    import uuid
                    request_id = str(uuid.uuid4())
                    self.approval_manager.create_request(
                        request_id=request_id,
                        message=f"Capability '{capability_name}' requires approval",
                        operation=capability_name,
                        step_id=action.node.id,
                        details={"params": action.node.params, "goal": context.get("goal", "")},
                    )
                    try:
                        approved = await self.approval_manager.wait_for_approval(request_id)
                    except TimeoutError:
                        approved = False

                    if not approved:
                        result.add_violation(
                            f"Capability '{capability_name}' requires approval but was rejected"
                        )
                    else:
                        result.add_approval_required(capability_name)
                else:
                    result.add_warning(
                        f"Capability '{capability_name}' requires approval but no ApprovalService configured"
                    )
                    result.add_approval_required(capability_name)

    def _check_workspace_isolation(
        self,
        patch: 'GraphPatch',
        result: ValidationResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Check that file operations stay within workspace root.
        Requirements: 31.8, 31.9
        """
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation

        # 优先使用运行时 context 里的 workspace_path（session 动态路径）
        # 降级到 config.workspace_root（静态初始化路径）
        workspace_path = (
            (context or {}).get("workspace_path")
            or self.config.workspace_root
        )
        if not workspace_path:
            return

        from pathlib import Path as _Path
        workspace_p = _Path(os.path.abspath(workspace_path))

        for action in patch.actions:
            if action.operation != PatchOperation.ADD_NODE or action.node is None:
                continue

            capability_name = action.node.capability_name
            # Check file-related capabilities
            if not any(capability_name.startswith(prefix) for prefix in ("fs.", "file", "python.run")):
                continue

            # Check path parameters
            for param_name, param_value in action.node.params.items():
                if not isinstance(param_value, str):
                    continue
                if not any(kw in param_name.lower() for kw in ("path", "file", "dir", "output")):
                    continue

                try:
                    # 相对路径以 workspace 为基准解析，绝对路径直接用
                    if os.path.isabs(param_value):
                        abs_path_p = _Path(os.path.normpath(param_value))
                    else:
                        abs_path_p = _Path(os.path.normpath(os.path.join(str(workspace_p), param_value)))
                    # 用 Path.is_relative_to 做路径包含检查（Windows 大小写不敏感，无 startswith 边界问题）
                    try:
                        abs_path_p.relative_to(workspace_p)
                    except ValueError:
                        result.add_violation(
                            f"Node '{action.node.id}' param '{param_name}' path '{param_value}' "
                            f"is outside workspace '{workspace_p}'"
                        )
                except Exception:
                    pass  # Skip non-path values

    def _check_cycles(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
        result: ValidationResult
    ) -> None:
        """
        Check that applying the patch would not create cycles.
        Requirements: 31.12, 31.13
        """
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        import copy

        # Build a lightweight adjacency map to simulate patch application
        # Use node_id -> set of target node_ids
        adj: Dict[str, set] = {nid: set() for nid in graph.nodes}

        for edge in graph.edges.values():
            adj.setdefault(edge.source_node, set()).add(edge.target_node)

        # Apply ADD_NODE and ADD_EDGE from patch
        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                adj[action.node.id] = set()
            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                adj.setdefault(action.edge.source_node, set()).add(action.edge.target_node)

        # DFS cycle detection
        visited: set = set()
        rec_stack: set = set()

        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            for neighbor in adj.get(node_id, set()):
                if neighbor not in visited:
                    if has_cycle(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            rec_stack.discard(node_id)
            return False

        for node_id in adj:
            if node_id not in visited:
                if has_cycle(node_id):
                    result.add_violation(
                        "Patch would create a cycle in the execution graph"
                    )
                    return

    @classmethod
    def from_config(cls, config_dict: Dict[str, Any], approval_manager: Optional['ApprovalService'] = None) -> 'PlannerGuard':
        """
        Create PlannerGuard from a configuration dictionary.

        Args:
            config_dict: Configuration dictionary (from security.yaml)
            approval_manager: Optional ApprovalManager instance

        Returns:
            Configured PlannerGuard instance
        """
        policies = []
        for cap_name, policy_cfg in config_dict.get("capability_policies", {}).items():
            action_str = policy_cfg.get("action", "allow")
            try:
                action = PolicyAction(action_str)
            except ValueError:
                action = PolicyAction.ALLOW
            policies.append(CapabilityPolicy(
                capability_name=cap_name,
                action=action,
                reason=policy_cfg.get("reason")
            ))

        config = GuardConfig(
            max_nodes_per_patch=config_dict.get("max_nodes_per_patch", 20),
            max_edges_per_patch=config_dict.get("max_edges_per_patch", 50),
            max_total_nodes=config_dict.get("max_total_nodes", 200),
            max_total_edges=config_dict.get("max_total_edges", 1000),
            workspace_root=config_dict.get("workspace_root"),
            enforce_workspace_isolation=config_dict.get("enforce_workspace_isolation", True),
            capability_policies=policies,
            default_policy=PolicyAction(config_dict.get("default_policy", "allow"))
        )

        return cls(config=config, approval_manager=approval_manager)
