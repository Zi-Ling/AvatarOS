"""Role management API — CRUD for custom worker roles.

Endpoints:
- GET  /roles           — list all registered roles (built-in + custom)
- POST /roles           — register a custom role (requires admin key if configured)
- DELETE /roles/{name}  — unregister a custom role (requires admin key if configured)
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/roles", tags=["roles"])

# Simple API key guard — set ROLE_ADMIN_KEY env var to enable
_ADMIN_KEY = os.environ.get("ROLE_ADMIN_KEY", "")


def _check_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    """Verify admin key for mutating operations. No-op if ROLE_ADMIN_KEY is not set."""
    if not _ADMIN_KEY:
        return  # No key configured — open access
    if x_admin_key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Key")


class RoleResponse(BaseModel):
    role_name: str
    system_prompt: str
    allowed_skills: List[str] = []
    prohibited_skills: List[str] = []
    budget_multiplier: float = 1.0
    is_builtin: bool = False


class CreateRoleRequest(BaseModel):
    role_name: str
    system_prompt: str
    allowed_skills: List[str] = []
    prohibited_skills: List[str] = []
    budget_multiplier: float = 1.0
    skill_reason: str = ""


@router.get("", response_model=List[RoleResponse])
async def list_roles():
    """List all registered roles."""
    from app.avatar.runtime.multiagent.roles.role_runners import (
        _ROLE_RUNNERS, _CUSTOM_SPECS,
    )

    roles: List[RoleResponse] = []

    # Built-in roles
    for name in _ROLE_RUNNERS:
        roles.append(RoleResponse(
            role_name=name,
            system_prompt="(built-in)",
            is_builtin=True,
        ))

    # Custom roles
    for name, spec in _CUSTOM_SPECS.items():
        roles.append(RoleResponse(
            role_name=name,
            system_prompt=spec.system_prompt,
            allowed_skills=sorted(spec.allowed_skills),
            prohibited_skills=sorted(spec.prohibited_skills),
            budget_multiplier=spec.budget_multiplier,
            is_builtin=False,
        ))

    return roles


@router.post("", response_model=RoleResponse, dependencies=[Depends(_check_admin)])
async def create_role(req: CreateRoleRequest):
    """Register a custom role and persist to DB."""
    import json
    from app.avatar.runtime.multiagent.roles.role_runners import (
        _ROLE_RUNNERS, register_role_runner, RoleRunnerSpec,
    )

    if req.role_name in _ROLE_RUNNERS:
        raise HTTPException(status_code=409, detail=f"Built-in role '{req.role_name}' cannot be overridden")

    spec = RoleRunnerSpec(
        role_name=req.role_name,
        system_prompt=req.system_prompt,
        allowed_skills=frozenset(req.allowed_skills),
        prohibited_skills=frozenset(req.prohibited_skills),
        budget_multiplier=req.budget_multiplier,
        skill_reason=req.skill_reason,
    )
    register_role_runner(spec)

    # Persist to DB
    try:
        from app.db.long_task_models import CustomRoleRecord
        from app.db.database import get_session
        record = CustomRoleRecord(
            role_name=req.role_name,
            system_prompt=req.system_prompt,
            allowed_skills_json=json.dumps(req.allowed_skills),
            prohibited_skills_json=json.dumps(req.prohibited_skills),
            budget_multiplier=req.budget_multiplier,
            skill_reason=req.skill_reason,
        )
        with get_session() as db:
            # Upsert: delete existing then insert
            from app.db.long_task_models import CustomRoleRecord as _CRR
            existing = db.get(_CRR, req.role_name)
            if existing:
                db.delete(existing)
                db.commit()
            db.add(record)
            db.commit()
    except Exception as e:
        logger.warning("[RoleAPI] DB persist failed: %s", e)

    return RoleResponse(
        role_name=spec.role_name,
        system_prompt=spec.system_prompt,
        allowed_skills=sorted(spec.allowed_skills),
        prohibited_skills=sorted(spec.prohibited_skills),
        budget_multiplier=spec.budget_multiplier,
        is_builtin=False,
    )


@router.delete("/{role_name}", dependencies=[Depends(_check_admin)])
async def delete_role(role_name: str):
    """Unregister a custom role and remove from DB."""
    from app.avatar.runtime.multiagent.roles.role_runners import (
        _ROLE_RUNNERS, _CUSTOM_SPECS, unregister_role_runner,
    )

    if role_name in _ROLE_RUNNERS:
        raise HTTPException(status_code=409, detail=f"Cannot delete built-in role '{role_name}'")

    if role_name not in _CUSTOM_SPECS:
        raise HTTPException(status_code=404, detail=f"Custom role '{role_name}' not found")

    unregister_role_runner(role_name)

    # Remove from DB
    try:
        from app.db.long_task_models import CustomRoleRecord
        from app.db.database import get_session
        with get_session() as db:
            record = db.get(CustomRoleRecord, role_name)
            if record:
                db.delete(record)
                db.commit()
    except Exception as e:
        logger.warning("[RoleAPI] DB delete failed: %s", e)

    return {"deleted": role_name}


def load_custom_roles_from_db() -> int:
    """Load persisted custom roles from DB and register them.

    Called during app startup. Returns count of loaded roles.
    """
    import json
    try:
        from app.db.long_task_models import CustomRoleRecord
        from app.db.database import get_session
        from app.avatar.runtime.multiagent.roles.role_runners import (
            register_role_runner, RoleRunnerSpec,
        )

        with get_session() as db:
            from sqlmodel import select
            records = list(db.exec(select(CustomRoleRecord)).all())

        count = 0
        for r in records:
            allowed = frozenset(json.loads(r.allowed_skills_json or "[]"))
            prohibited = frozenset(json.loads(r.prohibited_skills_json or "[]"))
            spec = RoleRunnerSpec(
                role_name=r.role_name,
                system_prompt=r.system_prompt,
                allowed_skills=allowed,
                prohibited_skills=prohibited,
                budget_multiplier=r.budget_multiplier,
                skill_reason=r.skill_reason,
            )
            register_role_runner(spec)
            count += 1

        if count > 0:
            logger.info("[RoleAPI] Loaded %d custom roles from DB", count)
        return count

    except Exception as e:
        logger.debug("[RoleAPI] Failed to load custom roles: %s", e)
        return 0


# ── YAML team config endpoint ───────────────────────────────────────

class LoadTeamRequest(BaseModel):
    yaml_path: str


@router.post("/team/load", dependencies=[Depends(_check_admin)])
async def load_team_config(req: LoadTeamRequest):
    """Load an agent team from a YAML configuration file."""
    from app.avatar.runtime.multiagent.config_loader.yaml_config import (
        load_team_config, apply_team_config,
    )
    try:
        team_cfg = load_team_config(req.yaml_path)
        result = apply_team_config(team_cfg)
        return {"team": team_cfg.name, **result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
