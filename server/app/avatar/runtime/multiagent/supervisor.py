"""Supervisor — 全局单例调度者，组合 4 个内聚子组件.

ComplexityEvaluator, InstanceManager, GraphValidator, TerminationEvaluator.
通过外部组合根注入所有依赖，Supervisor 不负责子系统注册。

Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 16.1-16.4, 25.1-25.3
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .agent_instance import AgentInstance, AgentInstanceStatus, TaskPacket
from .handoff_envelope import HandoffEnvelope
from .spawn_policy import SpawnPolicy
from .subtask_graph import SubtaskGraph
from .task_ownership import TaskOwnershipManager
from .trace_integration import TraceIntegration

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ComplexityAssessment
# ---------------------------------------------------------------------------

@dataclass
class ComplexityAssessment:
    """复杂度评估结果."""
    mode: str = "single_agent"  # "single_agent" | "multi_agent"
    estimated_subtask_count: int = 1
    needs_independent_verification: bool = False
    involves_multi_domain: bool = False
    reasoning: str = ""
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# 子组件 1: ComplexityEvaluator
# ---------------------------------------------------------------------------

class ComplexityEvaluator:
    """复杂度评估器.

    支持两种模式：
    - LLM 模式（llm_client 不为 None）：使用 LLM 判定任务复杂度
    - 规则模式（fallback）：基于关键词匹配的启发式判定

    LLM 调用失败时自动降级到规则模式。
    """

    # LLM 评估提示词
    _LLM_PROMPT = (
        "You are a task complexity analyzer. Given a user intent, determine if it "
        "requires single-agent or multi-agent execution.\n\n"
        "Criteria for multi_agent:\n"
        "- Task involves 3+ independent subtasks that can run in parallel\n"
        "- Task spans multiple domains (e.g., research + implement + test)\n"
        "- Task requires independent verification of results\n"
        "- Task is complex enough that decomposition improves quality\n\n"
        "Respond in JSON format ONLY:\n"
        '{"mode": "single_agent" or "multi_agent", '
        '"estimated_subtask_count": <int>, '
        '"needs_verification": <bool>, '
        '"involves_multi_domain": <bool>, '
        '"reasoning": "<brief explanation>", '
        '"confidence": <float 0-1>}\n\n'
        "User intent: {intent}"
    )

    def __init__(
        self,
        subtask_threshold: int = 3,
        multi_domain_keywords: Optional[List[str]] = None,
        llm_client: Optional[Any] = None,
    ) -> None:
        self.subtask_threshold = subtask_threshold
        self.multi_domain_keywords = multi_domain_keywords or [
            "research", "verify", "test", "deploy", "analyze",
            "design", "implement", "review", "integrate",
        ]
        self._llm_client = llm_client

    def evaluate(self, intent: str, env_context: Dict[str, Any]) -> ComplexityAssessment:
        """评估任务复杂度。优先使用 LLM，失败时降级到规则引擎。"""
        # Force flags 优先
        if env_context.get("force_multi_agent"):
            return ComplexityAssessment(
                mode="multi_agent", confidence=0.9,
                reasoning="force_multi_agent flag set",
            )
        if env_context.get("force_single_agent"):
            return ComplexityAssessment(
                mode="single_agent", confidence=0.9,
                reasoning="force_single_agent flag set",
            )

        # LLM 模式
        if self._llm_client is not None:
            try:
                return self._evaluate_with_llm(intent)
            except Exception as e:
                logger.warning(f"[ComplexityEvaluator] LLM evaluation failed, falling back to rules: {e}")

        # 规则模式（fallback）
        return self._evaluate_with_rules(intent, env_context)

    def _evaluate_with_llm(self, intent: str) -> ComplexityAssessment:
        """使用 LLM 评估复杂度。"""
        import json as _json

        prompt = self._LLM_PROMPT.format(intent=intent[:500])
        # 同步调用 LLM（ComplexityEvaluator 在同步上下文中使用）
        response = self._llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
        )

        # 解析 LLM 响应
        content = response.get("content", "") if isinstance(response, dict) else str(response)
        # 提取 JSON（可能被 markdown 包裹）
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = _json.loads(content.strip())

        return ComplexityAssessment(
            mode=data.get("mode", "single_agent"),
            estimated_subtask_count=data.get("estimated_subtask_count", 1),
            needs_independent_verification=data.get("needs_verification", False),
            involves_multi_domain=data.get("involves_multi_domain", False),
            reasoning=f"[LLM] {data.get('reasoning', '')}",
            confidence=data.get("confidence", 0.7),
        )

    def _evaluate_with_rules(self, intent: str, env_context: Dict[str, Any]) -> ComplexityAssessment:
        """基于规则评估任务复杂度（原始实现）。"""
        intent_lower = intent.lower()
        words = intent_lower.split()

        domain_hits = sum(
            1 for kw in self.multi_domain_keywords if kw in intent_lower
        )
        estimated_count = max(1, domain_hits)

        involves_multi_domain = domain_hits >= 2
        needs_verification = any(
            kw in intent_lower for kw in ("verify", "test", "validate", "check")
        )

        if len(words) > 50:
            estimated_count = max(estimated_count, 3)

        if estimated_count >= self.subtask_threshold:
            mode = "multi_agent"
            confidence = min(0.5 + domain_hits * 0.1, 0.9)
        else:
            mode = "single_agent"
            confidence = 0.7

        reasoning = (
            f"[rules] estimated_subtasks={estimated_count}, "
            f"multi_domain={involves_multi_domain}, "
            f"needs_verification={needs_verification}, "
            f"word_count={len(words)}"
        )

        return ComplexityAssessment(
            mode=mode,
            estimated_subtask_count=estimated_count,
            needs_independent_verification=needs_verification,
            involves_multi_domain=involves_multi_domain,
            reasoning=reasoning,
            confidence=confidence,
        )


# ---------------------------------------------------------------------------
# 子组件 2: InstanceManager
# ---------------------------------------------------------------------------

class InstanceManager:
    """实例生命周期管理器."""

    def __init__(
        self,
        spawn_policy: SpawnPolicy,
        role_registry: Any = None,
        task_ownership: Optional[TaskOwnershipManager] = None,
        trace: Optional[TraceIntegration] = None,
    ) -> None:
        self._spawn_policy = spawn_policy
        self._role_registry = role_registry
        self._task_ownership = task_ownership or TaskOwnershipManager()
        self._trace = trace
        self._instances: Dict[str, AgentInstance] = {}

    def spawn(
        self,
        role_name: str,
        task_id: str,
        runner: Any = None,
    ) -> Optional[AgentInstance]:
        """创建 Agent 实例."""
        active = self._get_active_counts()
        allowed, reason = self._spawn_policy.can_spawn(role_name, active)
        if not allowed:
            logger.warning(
                "[InstanceManager] spawn denied for %s: %s", role_name, reason
            )
            return None

        spec = None
        if self._role_registry is not None:
            spec = self._role_registry.get(role_name)
        if spec is None:
            from .role_spec import RoleSpec
            spec = RoleSpec(role_name=role_name, description=role_name)

        instance = AgentInstance(spec=spec, runner=runner)
        self._instances[instance.instance_id] = instance

        if self._trace:
            self._trace.agent_created(instance.instance_id, role_name, task_id)

        return instance

    def terminate(self, instance_id: str) -> None:
        """终止实例，回收任务."""
        instance = self._instances.get(instance_id)
        if instance is None:
            return
        # 回收任务
        reclaimed = self._task_ownership.reclaim(instance_id)
        final_state = instance.terminate()

        if self._trace:
            self._trace.agent_terminated(instance_id, instance.role_name)

        logger.info(
            "[InstanceManager] terminated %s, reclaimed tasks: %s",
            instance_id, reclaimed,
        )

    def get_active_instances(self) -> Dict[str, List[AgentInstance]]:
        """按角色分组返回活跃实例."""
        result: Dict[str, List[AgentInstance]] = {}
        for inst in self._instances.values():
            if inst.state.status not in (
                AgentInstanceStatus.TERMINATED,
            ):
                result.setdefault(inst.role_name, []).append(inst)
        return result

    def cleanup_idle(self) -> List[str]:
        """清理空闲实例."""
        terminated: List[str] = []
        for inst in list(self._instances.values()):
            if inst.check_idle():
                lp = getattr(inst.spec, "lifecycle_policy", None)
                if lp and lp.auto_terminate_on_idle:
                    idle_time = time.time() - inst.state.last_active_at
                    if idle_time > lp.idle_timeout_seconds:
                        self.terminate(inst.instance_id)
                        terminated.append(inst.instance_id)
        return terminated

    def _get_active_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for inst in self._instances.values():
            if inst.state.status not in (
                AgentInstanceStatus.TERMINATED,
            ):
                counts[inst.role_name] = counts.get(inst.role_name, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# 子组件 3: GraphValidator
# ---------------------------------------------------------------------------

class GraphValidator:
    """子任务图校验器.

    规则级强校验优先，规则能覆盖的场景不使用 LLM。
    """

    def __init__(self, role_registry: Any = None) -> None:
        self._role_registry = role_registry

    def validate_rules(self, graph: SubtaskGraph) -> tuple[bool, List[str]]:
        """规则级校验：DAG + 必填字段 + Schema 合规 + 角色权限."""
        all_errors: List[str] = []

        ok, errors = graph.validate_dag()
        if not ok:
            all_errors.extend(errors)

        ok, errors = graph.validate_required_fields()
        if not ok:
            all_errors.extend(errors)

        ok, errors = graph.validate_schema_compliance()
        if not ok:
            all_errors.extend(errors)

        if self._role_registry is not None:
            ok, errors = graph.validate_role_permissions(self._role_registry)
            if not ok:
                all_errors.extend(errors)

        return (len(all_errors) == 0, all_errors)

    async def validate_llm(self, graph: SubtaskGraph) -> tuple[bool, List[str]]:
        """可选的轻量级 LLM 逻辑校验. Phase 1 为占位."""
        return True, []


# ---------------------------------------------------------------------------
# 子组件 4: TerminationEvaluator
# ---------------------------------------------------------------------------

class TerminationEvaluator:
    """终态判定器.

    不支持多 Agent 降级为单 Agent，强制终止返回部分结果。
    """

    def __init__(
        self,
        max_rounds: int = 50,
        timeout_seconds: float = 3600.0,
    ) -> None:
        self.max_rounds = max_rounds
        self.timeout_seconds = timeout_seconds

    def check(
        self,
        current_round: int,
        start_time: float,
        graph: SubtaskGraph,
    ) -> bool:
        """检查是否应终止. 返回 True 表示应终止."""
        if graph.all_completed():
            return True
        if current_round >= self.max_rounds:
            logger.warning("[TerminationEvaluator] max rounds reached: %d", current_round)
            return True
        elapsed = time.monotonic() - start_time
        if elapsed >= self.timeout_seconds:
            logger.warning("[TerminationEvaluator] timeout: %.1fs", elapsed)
            return True
        return False

    def get_partial_results(self, graph: SubtaskGraph) -> Dict[str, Any]:
        """收集已完成节点的结果."""
        results: Dict[str, Any] = {}
        for nid, node in graph.nodes.items():
            if node.status == "completed" and node.result is not None:
                results[nid] = node.result
        return results


# ---------------------------------------------------------------------------
# Supervisor 主类
# ---------------------------------------------------------------------------

class Supervisor:
    """全局单例调度者，组合 4 个内聚子组件.

    通过外部组合根注入所有依赖，Supervisor 不负责子系统注册。
    """

    def __init__(
        self,
        role_registry: Any = None,
        spawn_policy: Optional[SpawnPolicy] = None,
        collaboration_hub: Any = None,
        budget_guard: Any = None,
        artifact_store: Any = None,
        graph_controller: Any = None,
        kernel: Any = None,
        trace: Optional[TraceIntegration] = None,
        complexity_threshold: int = 3,
        max_rounds: int = 50,
        timeout_seconds: float = 3600.0,
    ) -> None:
        self._role_registry = role_registry
        self._collaboration_hub = collaboration_hub
        self._budget_guard = budget_guard
        self._artifact_store = artifact_store
        self._graph_controller = graph_controller
        self._kernel = kernel

        _spawn_policy = spawn_policy or SpawnPolicy()
        _trace = trace or TraceIntegration()

        self._complexity = ComplexityEvaluator(subtask_threshold=complexity_threshold)
        self._instances = InstanceManager(
            spawn_policy=_spawn_policy,
            role_registry=role_registry,
            trace=_trace,
        )
        self._validator = GraphValidator(role_registry=role_registry)
        self._termination = TerminationEvaluator(
            max_rounds=max_rounds,
            timeout_seconds=timeout_seconds,
        )
        self._trace = _trace
        self._current_graph: Optional[SubtaskGraph] = None
        self._start_time: float = 0.0
        self._current_round: int = 0

    # ------------------------------------------------------------------
    # 委托方法
    # ------------------------------------------------------------------

    def evaluate_complexity(
        self, intent: str, env_context: Dict[str, Any]
    ) -> ComplexityAssessment:
        return self._complexity.evaluate(intent, env_context)

    def spawn_agent(
        self, role_name: str, task_id: str, runner: Any = None
    ) -> Optional[AgentInstance]:
        return self._instances.spawn(role_name, task_id, runner)

    def evaluate_termination(self) -> bool:
        if self._current_graph is None:
            return True
        return self._termination.check(
            self._current_round, self._start_time, self._current_graph
        )

    # ------------------------------------------------------------------
    # Supervisor 自身职责
    # ------------------------------------------------------------------

    def resolve_conflict(self, resource_id: str, contenders: List[str]) -> str:
        """冲突裁决：简单优先级策略."""
        if not contenders:
            return ""
        # Phase 1: 先到先得
        return contenders[0]

    def synthesize_results(self, graph: SubtaskGraph) -> Dict[str, Any]:
        """汇总结果."""
        results = self._termination.get_partial_results(graph)
        return {
            "status": "completed" if graph.all_completed() else "partial",
            "node_results": results,
            "total_nodes": len(graph.nodes),
            "completed_nodes": sum(
                1 for n in graph.nodes.values() if n.status == "completed"
            ),
        }

    # ------------------------------------------------------------------
    # 状态快照（Phase 1 仅 to_dict 级别）
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """导出状态快照."""
        active = self._instances.get_active_instances()
        instance_states = {}
        for role, instances in active.items():
            instance_states[role] = [inst.state.to_dict() for inst in instances]

        return {
            "current_round": self._current_round,
            "start_time": self._start_time,
            "active_instances": instance_states,
            "graph": {
                "graph_id": self._current_graph.graph_id if self._current_graph else "",
                "nodes": {
                    nid: {
                        "status": n.status,
                        "responsible_role": n.responsible_role,
                    }
                    for nid, n in (self._current_graph.nodes if self._current_graph else {}).items()
                },
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], **kwargs: Any) -> Supervisor:
        """从快照重建 Supervisor（Phase 1 基础版本）."""
        supervisor = cls(**kwargs)
        supervisor._current_round = data.get("current_round", 0)
        supervisor._start_time = data.get("start_time", 0.0)
        return supervisor
