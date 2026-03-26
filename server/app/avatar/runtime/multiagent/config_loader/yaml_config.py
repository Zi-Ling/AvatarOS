"""YAML declarative configuration loader for Agent Teams.

Parses a YAML file defining agents, subagents, routing rules, and team
settings into the runtime's native config objects (MultiAgentConfig,
RoleRunnerSpec, SubtaskGraph).

Example YAML:
    name: research-team
    agents:
      coordinator:
        model: claude-3-5-sonnet
        system: "You are the coordinator..."
        subagents: [researcher, writer]
      researcher:
        model: gpt-4o-mini
        system: "You are a researcher..."
        skills: [web-search, fs-read]
        budget_multiplier: 0.5
      writer:
        model: claude-3-opus
        system: "You are a writer..."
        skills: [fs-write, fs-read]
    team:
      coordination_mode: orchestrator
      max_parallel_agents: 3
      timeout: 300
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentTeamConfig:
    """Parsed agent team configuration from YAML."""
    name: str = ""
    coordination_mode: str = "orchestrator"  # orchestrator / peer_to_peer / hierarchical
    max_parallel_agents: int = 4
    timeout_seconds: float = 300.0
    shared_memory: bool = True
    agents: Dict[str, "AgentSpec"] = field(default_factory=dict)
    orchestrator_id: str = ""


@dataclass
class AgentSpec:
    """Single agent specification from YAML."""
    agent_id: str = ""
    model: str = ""
    system_prompt: str = ""
    skills: List[str] = field(default_factory=list)
    subagents: List[str] = field(default_factory=list)
    budget_multiplier: float = 1.0
    timeout_seconds: float = 60.0
    max_retries: int = 2


def load_team_config(yaml_path: str) -> AgentTeamConfig:
    """Load and validate an agent team YAML configuration.

    Args:
        yaml_path: path to the YAML file

    Returns:
        Parsed AgentTeamConfig

    Raises:
        FileNotFoundError: if YAML file doesn't exist
        ValueError: if YAML is invalid or missing required fields
    """
    import yaml

    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"Team config not found: {yaml_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError("Team config must be a YAML mapping")

    team_cfg = AgentTeamConfig(
        name=raw.get("name", path.stem),
    )

    # Parse team settings
    team = raw.get("team", {})
    team_cfg.coordination_mode = team.get("coordination_mode", "orchestrator")
    team_cfg.max_parallel_agents = team.get("max_parallel_agents", 4)
    team_cfg.timeout_seconds = float(team.get("timeout", 300))
    team_cfg.shared_memory = team.get("shared_memory", True)

    # Parse agents
    agents_raw = raw.get("agents", {})
    for agent_id, agent_data in agents_raw.items():
        if not isinstance(agent_data, dict):
            continue
        spec = AgentSpec(
            agent_id=agent_id,
            model=agent_data.get("model", ""),
            system_prompt=agent_data.get("system", ""),
            skills=agent_data.get("skills", []),
            subagents=agent_data.get("subagents", []),
            budget_multiplier=float(agent_data.get("budget_multiplier", 1.0)),
            timeout_seconds=float(agent_data.get("timeout", "60").rstrip("s")),
            max_retries=int(agent_data.get("max_retries", 2)),
        )
        team_cfg.agents[agent_id] = spec

        # Auto-detect orchestrator
        if spec.subagents:
            team_cfg.orchestrator_id = agent_id

    # Validate
    if not team_cfg.agents:
        raise ValueError("Team config must define at least one agent")

    if team_cfg.coordination_mode == "orchestrator" and not team_cfg.orchestrator_id:
        # Use first agent as orchestrator
        team_cfg.orchestrator_id = next(iter(team_cfg.agents))

    logger.info(
        "[YAMLConfig] Loaded team '%s': %d agents, mode=%s, orchestrator=%s",
        team_cfg.name, len(team_cfg.agents),
        team_cfg.coordination_mode, team_cfg.orchestrator_id,
    )
    return team_cfg


def apply_team_config(team_cfg: AgentTeamConfig) -> Dict[str, Any]:
    """Apply a parsed team config: register custom roles and return runtime params.

    Returns dict with keys: coordination_mode, max_parallel, timeout, roles_registered.
    """
    from app.avatar.runtime.multiagent.roles.role_runners import register_role_runner, RoleRunnerSpec
    from app.avatar.runtime.multiagent.config import MultiAgentConfig

    registered = []
    for agent_id, spec in team_cfg.agents.items():
        # Skip the orchestrator — it's handled by SupervisorRuntime
        if agent_id == team_cfg.orchestrator_id:
            continue
        if not spec.system_prompt:
            continue

        role_spec = RoleRunnerSpec(
            role_name=agent_id,
            system_prompt=spec.system_prompt,
            allowed_skills=frozenset(spec.skills) if spec.skills else frozenset(),
            budget_multiplier=spec.budget_multiplier,
        )
        register_role_runner(role_spec)
        registered.append(agent_id)

    logger.info("[YAMLConfig] Applied team '%s': registered %d roles", team_cfg.name, len(registered))

    return {
        "coordination_mode": team_cfg.coordination_mode,
        "max_parallel": team_cfg.max_parallel_agents,
        "timeout": team_cfg.timeout_seconds,
        "shared_memory": team_cfg.shared_memory,
        "roles_registered": registered,
        "orchestrator": team_cfg.orchestrator_id,
    }
