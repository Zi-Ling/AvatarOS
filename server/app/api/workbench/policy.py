# app/api/policy.py
"""
Policy Console API

GET  /policy/config          — 读取当前 GuardConfig（capability_policies + limits）
PUT  /policy/config          — 更新 GuardConfig（运行时热更新，重启后恢复默认）
GET  /policy/skills          — 列出所有已注册 skill 及其当前 policy action
POST /policy/simulate        — 模拟一个 skill 调用，返回 guard 决策（allow/deny/require_approval）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/policy", tags=["policy"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_guard():
    """从全局 AvatarMain 取 PlannerGuard 实例。"""
    from app.core.bootstrap import get_avatar_main
    main = get_avatar_main()
    if main is None or not hasattr(main, "_graph_controller") or main._graph_controller is None:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    ctrl = main._graph_controller
    if not hasattr(ctrl, "guard") or ctrl.guard is None:
        raise HTTPException(status_code=503, detail="PlannerGuard not available")
    return ctrl.guard


def _config_to_dict(guard) -> dict:
    cfg = guard.config
    return {
        "max_nodes_per_patch": cfg.max_nodes_per_patch,
        "max_edges_per_patch": cfg.max_edges_per_patch,
        "max_total_nodes": cfg.max_total_nodes,
        "max_total_edges": cfg.max_total_edges,
        "workspace_root": cfg.workspace_root,
        "enforce_workspace_isolation": cfg.enforce_workspace_isolation,
        "default_policy": cfg.default_policy.value,
        "capability_policies": [
            {
                "capability_name": p.capability_name,
                "action": p.action.value,
                "reason": p.reason,
            }
            for p in cfg.capability_policies
        ],
    }


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CapabilityPolicyItem(BaseModel):
    capability_name: str
    action: str          # allow | deny | require_approval
    reason: Optional[str] = None


class PolicyConfigUpdate(BaseModel):
    max_nodes_per_patch: Optional[int] = None
    max_edges_per_patch: Optional[int] = None
    max_total_nodes: Optional[int] = None
    max_total_edges: Optional[int] = None
    enforce_workspace_isolation: Optional[bool] = None
    default_policy: Optional[str] = None
    capability_policies: Optional[List[CapabilityPolicyItem]] = None


class SimulateRequest(BaseModel):
    skill_name: str
    params: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/config")
async def get_policy_config():
    """返回当前 PlannerGuard 配置（capability policies + resource limits）。"""
    guard = _get_guard()
    return _config_to_dict(guard)


@router.put("/config")
async def update_policy_config(body: PolicyConfigUpdate):
    """
    运行时热更新 PlannerGuard 配置。
    仅更新传入的字段，未传入的字段保持不变。
    注意：重启后恢复默认值（持久化配置文件功能待后续实现）。
    """
    from app.avatar.runtime.graph.guard.planner_guard import PolicyAction, CapabilityPolicy

    guard = _get_guard()
    cfg = guard.config

    if body.max_nodes_per_patch is not None:
        cfg.max_nodes_per_patch = body.max_nodes_per_patch
    if body.max_edges_per_patch is not None:
        cfg.max_edges_per_patch = body.max_edges_per_patch
    if body.max_total_nodes is not None:
        cfg.max_total_nodes = body.max_total_nodes
    if body.max_total_edges is not None:
        cfg.max_total_edges = body.max_total_edges
    if body.enforce_workspace_isolation is not None:
        cfg.enforce_workspace_isolation = body.enforce_workspace_isolation
    if body.default_policy is not None:
        try:
            cfg.default_policy = PolicyAction(body.default_policy)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid policy action: {body.default_policy}")
    if body.capability_policies is not None:
        new_policies = []
        for item in body.capability_policies:
            try:
                action = PolicyAction(item.action)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid action '{item.action}' for {item.capability_name}")
            new_policies.append(CapabilityPolicy(
                capability_name=item.capability_name,
                action=action,
                reason=item.reason,
            ))
        cfg.capability_policies = new_policies
        guard._policy_map = {p.capability_name: p for p in new_policies}

    logger.info(f"[PolicyAPI] Config updated: {_config_to_dict(guard)}")
    return {"success": True, "config": _config_to_dict(guard)}


@router.get("/skills")
async def list_skills_with_policy():
    """
    列出所有已注册 skill，附带当前 policy action。
    用于 Policy Console 的技能列表视图。
    """
    from app.avatar.skills.registry import skill_registry
    from app.avatar.runtime.graph.guard.planner_guard import PolicyAction

    guard = _get_guard()
    cfg = guard.config

    skills = []
    for skill_cls in skill_registry.iter_skills():
        spec = skill_cls.spec
        name = spec.name
        policy = guard._policy_map.get(name)
        action = policy.action.value if policy else cfg.default_policy.value
        reason = policy.reason if policy else None

        side_effects = [se.value for se in getattr(spec, "side_effects", set())]
        risk_level = getattr(spec, "risk_level", None)

        skills.append({
            "name": name,
            "description": spec.description,
            "risk_level": risk_level.value if risk_level else None,
            "side_effects": side_effects,
            "policy_action": action,
            "policy_reason": reason,
            "is_custom_policy": name in guard._policy_map,
        })

    skills.sort(key=lambda s: s["name"])
    return {"count": len(skills), "skills": skills}


@router.post("/simulate")
async def simulate_policy(body: SimulateRequest):
    """
    模拟一个 skill 调用，返回 guard 决策（不实际执行）。
    用于 Policy Console 的调试面板。
    """
    from app.avatar.runtime.graph.guard.planner_guard import PolicyAction
    from app.avatar.skills.registry import skill_registry

    guard = _get_guard()
    cfg = guard.config

    skill_cls = skill_registry.get(body.skill_name)
    if skill_cls is None:
        return {
            "skill_name": body.skill_name,
            "decision": "deny",
            "reason": f"Skill '{body.skill_name}' not found in registry",
            "found": False,
        }

    policy = guard._policy_map.get(body.skill_name)
    if policy is None:
        action = cfg.default_policy
        reason = f"No explicit policy — using default: {action.value}"
    else:
        action = policy.action
        reason = policy.reason or f"Explicit policy: {action.value}"

    # 简单路径检查（workspace isolation）
    workspace_violation = None
    if cfg.enforce_workspace_isolation and cfg.workspace_root:
        import os
        from pathlib import Path
        ws = Path(os.path.abspath(cfg.workspace_root))
        for k, v in body.params.items():
            if isinstance(v, str) and os.path.isabs(v):
                try:
                    Path(os.path.normpath(v)).relative_to(ws)
                except ValueError:
                    workspace_violation = f"Path '{v}' is outside workspace '{ws}'"
                    break

    return {
        "skill_name": body.skill_name,
        "found": True,
        "decision": action.value,
        "reason": reason,
        "workspace_violation": workspace_violation,
        "effective_action": "deny" if workspace_violation else action.value,
    }
