"""
GraphController - Orchestration layer for graph execution

This module coordinates GraphPlanner and GraphRuntime to execute graphs:
- ReAct mode: Iterative planning and execution
- DAG mode: One-shot planning then execution
- Enforces global limits (max concurrent graphs, max planner invocations)
- Integrates PlannerGuard for safety validation

Requirements: 26.1-26.14
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from enum import Enum
import logging
import re
import asyncio
from datetime import datetime, timezone

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.planner.graph_planner import GraphPlanner
    from app.avatar.runtime.graph.runtime.graph_runtime import GraphRuntime, ExecutionResult
    from app.avatar.runtime.graph.guard.planner_guard import PlannerGuard

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """Graph execution mode"""
    REACT = "react"  # Iterative planning
    DAG = "dag"  # One-shot planning


class GraphController:
    """
    Orchestration layer for graph execution.
    
    GraphController coordinates:
    1. GraphPlanner: Generates execution plans
    2. PlannerGuard: Validates plans for safety
    3. GraphRuntime: Executes validated plans
    
    Supports two execution modes:
    - ReAct: Iterative planning (plan → execute → observe → plan)
    - DAG: One-shot planning (plan complete graph → execute all)
    
    Enforces global limits:
    - max_concurrent_graphs: Maximum concurrent graph executions
    - max_planner_invocations_per_graph: Maximum planner calls per graph
    
    Requirements:
    - 26.1: Coordinate GraphPlanner and GraphRuntime
    - 26.2: Support ReAct mode
    - 26.3: Support DAG mode
    - 26.4: Enforce max_concurrent_graphs limit
    - 26.5: Enforce max_planner_invocations_per_graph limit
    - 26.6: Track planner usage (tokens, calls, cost)
    - 26.7: Provide execute() API
    - 26.8: Integrate PlannerGuard
    - 26.9: Apply validated patches to graph
    """
    
    def __init__(
        self,
        planner: 'GraphPlanner',
        runtime: 'GraphRuntime',
        guard: Optional['PlannerGuard'] = None,
        max_concurrent_graphs: int = 10,
        max_planner_invocations_per_graph: int = 200,
        max_planner_tokens: Optional[int] = None,
        max_planner_calls: Optional[int] = None,
        max_planner_cost: Optional[float] = None,
        max_execution_cost: Optional[float] = None,
    ):
        """
        Initialize GraphController.
        
        Args:
            planner: GraphPlanner for generating plans
            runtime: GraphRuntime for executing graphs
            guard: Optional PlannerGuard for safety validation
            max_concurrent_graphs: Maximum concurrent graph executions
            max_planner_invocations_per_graph: Maximum planner calls per graph
            max_planner_tokens: Maximum total tokens across all planner calls
            max_planner_calls: Maximum total planner calls
            max_planner_cost: Maximum total planner cost in USD
            max_execution_cost: Maximum total execution cost in USD
        """
        self.planner = planner
        self.runtime = runtime
        self.guard = guard
        self.max_concurrent_graphs = max_concurrent_graphs
        self.max_planner_invocations_per_graph = max_planner_invocations_per_graph
        self.max_planner_tokens = max_planner_tokens
        self.max_planner_calls = max_planner_calls
        self.max_planner_cost = max_planner_cost
        self.max_execution_cost = max_execution_cost
        
        # Track active graphs
        self._active_graphs: Dict[str, asyncio.Task] = {}
        self._graph_semaphore = asyncio.Semaphore(max_concurrent_graphs)
        
        # Track planner usage (Requirements 26.6, 26.10, 26.11, 26.12)
        self._planner_usage = {
            'total_tokens': 0,
            'total_calls': 0,
            'total_cost': 0.0,
        }
        
        logger.info(
            f"GraphController initialized: "
            f"max_concurrent_graphs={max_concurrent_graphs}, "
            f"max_planner_invocations={max_planner_invocations_per_graph}, "
            f"max_tokens={max_planner_tokens}, max_calls={max_planner_calls}, "
            f"max_cost={max_planner_cost}, max_execution_cost={max_execution_cost}"
        )

    @staticmethod
    def _make_error_result(graph: 'ExecutionGraph', error_message: str) -> 'ExecutionResult':
        """构造失败的 ExecutionResult（替代不存在的 runtime._create_result）"""
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
        return ExecutionResult(
            success=False,
            final_status="failed",
            error_message=error_message,
            graph=graph,
        )
    
    async def execute(
        self,
        intent: str,
        mode: ExecutionMode = ExecutionMode.REACT,
        env_context: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        control_handle: Optional[Any] = None,
    ) -> 'ExecutionResult':
        """
        Execute a graph from intent.

        Args:
            intent: High-level goal description
            mode: Execution mode (REACT or DAG)
            env_context: Environment context (workspace, skills, session metadata, etc.)
            config: Optional configuration overrides
            control_handle: TaskControlHandle for cancel/pause/resume control.
                            Kept separate from env_context to avoid semantic pollution.

        Returns:
            ExecutionResult with execution outcome

        Requirements: 26.1, 26.2, 26.3, 26.4, 26.7
        """
        env_context = env_context or {}
        config = config or {}

        # Enforce concurrent graph limit
        async with self._graph_semaphore:
            if mode == ExecutionMode.REACT:
                return await self._execute_react_mode(intent, env_context, config, control_handle)
            elif mode == ExecutionMode.DAG:
                return await self._execute_dag_mode(intent, env_context, config)
            else:
                raise ValueError(f"Unknown execution mode: {mode}")
    
    async def _execute_react_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
        control_handle: Optional[Any] = None,
    ) -> 'ExecutionResult':
        """
        Execute in ReAct mode (iterative planning).

        control_handle: TaskControlHandle，提供 cancel/pause/resume 控制。
        不从 env_context 读取控制信号，保持 env_context 语义纯净（仅环境上下文）。
        """
        import time
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        from app.avatar.runtime.graph.lifecycle.execution_lifecycle import ExecutionLifecycle
        from app.services.session_store import ExecutionSessionStore, InvalidTransitionError

        max_react_iterations = config.get('max_react_iterations', 200)
        max_graph_nodes = config.get('max_graph_nodes', 200)

        # 创建 ExecutionSession
        _workspace_path = env_context.get("workspace_path") or (
            str(self.guard.config.workspace_root)
            if self.guard and self.guard.config.workspace_root else ""
        )
        _policy_snap = None
        _runtime_config_snap = {
            "max_concurrent_graphs": self.max_concurrent_graphs,
            "max_planner_invocations_per_graph": self.max_planner_invocations_per_graph,
            "max_planner_tokens": self.max_planner_tokens,
            "max_planner_calls": self.max_planner_calls,
            "max_planner_cost": self.max_planner_cost,
            "max_execution_cost": self.max_execution_cost,
            "max_react_iterations": max_react_iterations,
            "max_graph_nodes": max_graph_nodes,
        }
        if self.guard:
            _policy_snap = {
                "workspace_root": str(self.guard.config.workspace_root),
                "enforce_workspace_isolation": self.guard.config.enforce_workspace_isolation,
                "default_policy": self.guard.config.default_policy,
                "max_nodes_per_patch": self.guard.config.max_nodes_per_patch,
            }
        _exec_session = ExecutionSessionStore.create(
            goal=intent,
            run_id=env_context.get("run_id"),
            task_id=env_context.get("task_id"),
            request_id=env_context.get("request_id"),
            trace_id=env_context.get("trace_id"),
            conversation_id=env_context.get("session_id"),  # chat session_id → conversation_id
            workspace_path=_workspace_path,
            policy_snapshot=_policy_snap,
            runtime_config_snapshot=_runtime_config_snap,
        )
        _exec_session_id = _exec_session.id
        _lifecycle = ExecutionLifecycle(_exec_session_id)
        await _lifecycle.on_session_start()

        # 把 exec_session_id 写入 env_context，供 guard 创建 Grant 和 executor 查 Grant 时使用
        env_context = dict(env_context)
        env_context["exec_session_id"] = _exec_session_id

        # Create empty graph
        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
        graph.metadata["session_id"] = env_context.get("session_id")
        graph.metadata["env"] = env_context

        on_graph_created = env_context.get("on_graph_created")
        if on_graph_created:
            try:
                on_graph_created(str(graph.id))
            except Exception as _e:
                logger.warning(f"[GraphController] on_graph_created failed: {_e}")

        from app.avatar.runtime.graph.context.execution_context import ExecutionContext as _ExecCtx
        _session_id = env_context.get("session_id")
        _workspace = None
        if _session_id:
            try:
                from app.avatar.runtime.workspace import get_session_workspace_manager
                _ws_mgr = get_session_workspace_manager()
                if _ws_mgr is not None:
                    _workspace = _ws_mgr.get_or_create(_session_id)
            except Exception:
                pass
        _shared_context = _ExecCtx(
            graph_id=graph.id,
            goal_desc=intent,
            inputs=env_context,
            session_id=_exec_session_id,  # ExecutionSession.id，用于 StepTraceRecord 关联
            task_id=graph.id,
            env=env_context,
            workspace=_workspace,
        )

        sub_goals = self._decompose_goal(intent)
        logger.info(f"[GoalTracker] Decomposed '{intent}' into {len(sub_goals)} sub-goals: {sub_goals}")

        planner_invocations = 0
        # control_handle 提供 cancel/pause/resume 控制原语
        # 不从 env_context 读取，保持 env_context 语义纯净
        _handle = control_handle

        # outcome 变量：统一 finally 出口通过它决定 lifecycle/result_status
        _lifecycle_status = "failed"
        _result_status = "unknown"
        _error_message: Optional[str] = None
        _final_result: Optional['ExecutionResult'] = None

        try:
            while True:
                # 1. 取消检查
                if _handle is not None and _handle.is_cancelled():
                    logger.info("[GraphController] Cancellation signal received")
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _lifecycle_status = "cancelled"
                    _result_status = "cancelled"
                    _error_message = "Task cancelled by user"
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                # 2. 暂停检查（阻塞直到恢复，在每轮 ReAct 循环边界生效）
                if _handle is not None:
                    await _handle.wait_if_paused()
                    # 恢复后再检查一次取消
                    if _handle.is_cancelled():
                        logger.info("[GraphController] Cancellation signal received after resume")
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _lifecycle_status = "cancelled"
                        _result_status = "cancelled"
                        _error_message = "Task cancelled by user"
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # 2. Limit 检查
                if planner_invocations >= self.max_planner_invocations_per_graph:
                    _error_message = f"Exceeded max planner invocations: {planner_invocations}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                if planner_invocations >= max_react_iterations:
                    _error_message = f"Exceeded max ReAct iterations: {planner_invocations}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                if len(graph.nodes) >= max_graph_nodes:
                    _error_message = f"Exceeded max graph nodes: {len(graph.nodes)}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                # 3. Planner budget 检查
                budget_error = self._check_planner_budget()
                if budget_error:
                    _error_message = f"Planner budget exceeded: {budget_error}"
                    logger.error(_error_message)
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph.status = GraphStatus.FAILED
                    _final_result = self._make_error_result(graph, error_message=_error_message)
                    return _final_result

                # 4. Plan
                planner_invocations += 1
                logger.info(f"Planner invocation {planner_invocations}/{self.max_planner_invocations_per_graph}")
                _plan_start = time.monotonic()
                patch = await self.planner.plan_next_step(graph, env_context)
                _plan_latency_ms = int((time.monotonic() - _plan_start) * 1000)

                self._track_planner_usage(patch)
                _patch_meta = (patch.metadata or {}) if patch else {}

                is_finish = patch is None or (
                    len(patch.actions) == 1 and
                    patch.actions[0].operation == PatchOperation.FINISH
                )

                if not is_finish:
                    # 有效 plan：触发 lifecycle（首次触发 created->planned）
                    await _lifecycle.on_plan_generated(
                        planner_input={"goal": intent, "graph_nodes": len(graph.nodes)},
                        planner_output={"actions": len(patch.actions)},
                        tokens_used=_patch_meta.get("tokens_used", 0),
                        cost_usd=_patch_meta.get("cost", 0.0),
                        latency_ms=_plan_latency_ms,
                    )

                if is_finish:
                    logger.info("Planner returned FINISH")
                    uncovered = self._get_uncovered_sub_goals(sub_goals, graph)
                    if uncovered:
                        logger.warning(
                            f"[GoalTracker] FINISH rejected: {len(uncovered)} sub-goal(s) uncovered: {uncovered}"
                        )
                        env_context = dict(env_context)
                        env_context["uncovered_sub_goals"] = uncovered
                        env_context["goal_tracker_hint"] = (
                            f"The following sub-goals are NOT yet completed: {uncovered}. "
                            f"You MUST complete them before finishing."
                        )
                        continue
                    logger.info("Planner returned FINISH -- all sub-goals covered")
                    break

                # 5. Guard validate
                if self.guard:
                    validation = await self.guard.validate(patch, graph, context=env_context)
                    await _lifecycle.on_policy_evaluated(
                        approved=validation.approved,
                        violations=validation.violations,
                        warnings=validation.warnings,
                        requires_approval=validation.requires_approval,
                    )
                    if not validation.approved:
                        _error_message = f"Patch validation failed: {validation.violations}"
                        logger.error(_error_message)
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # 6. Apply patch
                self._apply_patch(patch, graph)
                self._emit_plan_generated(graph, env_context)

                # ParamBinder
                resolved_inputs = env_context.get("resolved_inputs")
                if resolved_inputs:
                    from app.avatar.runtime.context.param_binder import bind_params
                    for node in graph.nodes.values():
                        if node.status == NodeStatus.PENDING and node.params is not None:
                            bound, binding_log = bind_params(
                                skill_name=node.capability_name,
                                params=node.params,
                                resolved_inputs=resolved_inputs,
                            )
                            if binding_log:
                                node.params = bound
                                logger.info(
                                    f"[ParamBinder] {node.capability_name}: "
                                    f"bound {len(binding_log)} param(s): "
                                    f"{[b['param'] for b in binding_log]}"
                                )

                # 7. 第一个节点执行前触发 planned -> running
                await _lifecycle.on_execution_started()

                # 8. Execute ready nodes
                result = await self.runtime.execute_ready_nodes(graph, context=_shared_context)

                # llm.fallback terminal
                last_nodes = [n for n in graph.nodes.values() if n.capability_name == "llm.fallback"]
                if last_nodes and any(n.status == NodeStatus.SUCCESS for n in last_nodes):
                    logger.info("[GraphController] llm.fallback succeeded -- terminating ReAct loop")
                    break

                # 9. Execution cost budget
                if self.max_execution_cost:
                    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
                    if not hasattr(graph, '_context'):
                        graph._context = ExecutionContext(graph_id=graph.id)
                    current_cost = self.runtime.get_execution_cost(graph, graph._context)
                    if current_cost >= self.max_execution_cost:
                        _error_message = (
                            f"Execution cost budget exceeded: ${current_cost:.4f} >= "
                            f"${self.max_execution_cost:.4f}"
                        )
                        logger.error(f"[GraphController] {_error_message}")
                        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                        graph.status = GraphStatus.FAILED
                        _final_result = self._make_error_result(graph, error_message=_error_message)
                        return _final_result

                # 10. Terminal check
                if result.final_status in ("failed", "partial_success"):
                    _final_result = result
                    return _final_result

                if result.final_status == "success":
                    uncovered = self._get_uncovered_sub_goals(sub_goals, graph)
                    if uncovered:
                        logger.warning(
                            f"[GoalTracker] Runtime success but {len(uncovered)} sub-goal(s) "
                            f"uncovered: {uncovered} -- continuing ReAct loop"
                        )
                        env_context = dict(env_context)
                        env_context["uncovered_sub_goals"] = uncovered
                        env_context["goal_tracker_hint"] = (
                            f"The following sub-goals are NOT yet completed: {uncovered}. "
                            f"You MUST complete them before finishing."
                        )
                        continue
                    logger.debug("[ReAct] Node(s) succeeded, continuing loop for Planner FINISH decision")

            # FINISH 后计算最终结果
            completed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
            failed = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
            skipped = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
            final_status = self.runtime._compute_graph_status(graph)

            from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
            _final_result = ExecutionResult(
                success=final_status in ("success", "partial_success"),
                final_status=final_status,
                completed_nodes=completed,
                failed_nodes=failed,
                skipped_nodes=skipped,
                graph=graph,
            )
            return _final_result

        finally:
            # 统一出口：根据 _final_result 决定 lifecycle/result_status
            if _final_result is not None:
                fs = _final_result.final_status
                if fs == "success":
                    _lifecycle_status = "completed"
                    _result_status = "success"
                elif fs == "partial_success":
                    _lifecycle_status = "completed"
                    _result_status = "partial_success"
                elif fs == "failed":
                    _lifecycle_status = "failed"
                    _result_status = "failed"
                # cancelled 已在 return 前设置，不覆盖

            _ns = NodeStatus
            _total = len(graph.nodes)
            _completed_n = sum(1 for n in graph.nodes.values() if n.status == _ns.SUCCESS)
            _failed_n = sum(1 for n in graph.nodes.values() if n.status == _ns.FAILED)

            await _lifecycle.on_session_end(
                lifecycle_status=_lifecycle_status,
                result_status=_result_status,
                total_nodes=_total,
                completed_nodes=_completed_n,
                failed_nodes=_failed_n,
                error_message=_error_message,
            )

    async def _execute_dag_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> 'ExecutionResult':
        """
        Execute in DAG mode (one-shot planning).
        
        DAG mode:
        1. Plan complete graph (with auto-repair on simple errors)
        2. Validate patch
        3. Apply patch to graph
        4. Execute entire graph
        
        Auto-repair attempts:
        - Fix duplicate node IDs
        - Fix invalid field references
        - Fix missing edges
        - Limit planning attempts to 3
        
        Requirements: 26.3, 26.8, 26.9, 20.5, 20.6, 20.7, 20.8
        """
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
        
        max_planning_attempts = 3
        planning_attempt = 0
        
        while planning_attempt < max_planning_attempts:
            planning_attempt += 1
            
            # 1. Plan complete graph
            logger.info(f"Planning complete graph (DAG mode, attempt {planning_attempt}/{max_planning_attempts})")
            patch = await self.planner.plan_complete_graph(intent, env_context)
            
            # Try auto-repair for simple errors (Requirements 20.5, 20.6, 20.7)
            repair_result = self._auto_repair_dag(patch)
            if repair_result['repaired']:
                logger.info(f"Auto-repaired DAG: {repair_result['repairs']}")
                patch = repair_result['patch']
            
            # 2. Validate patch
            if self.guard:
                _empty_graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                validation = await self.guard.validate(patch, _empty_graph, context=env_context)
                
                if not validation.approved:
                    logger.error(f"Patch validation failed: {validation.violations}")
                    
                    # If auto-repair failed and we have attempts left, request new plan (Requirement 20.8)
                    if planning_attempt < max_planning_attempts:
                        logger.warning(f"Requesting new plan (attempt {planning_attempt + 1}/{max_planning_attempts})")
                        continue
                    
                    # No more attempts, fail
                    from app.avatar.runtime.graph.models.execution_graph import GraphStatus
                    graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                    graph.status = GraphStatus.FAILED
                    return self._make_error_result(
                        graph,
                        error_message=f"Patch validation failed after {max_planning_attempts} attempts: {validation.violations}"
                    )
            
            # 3. Apply patch to create graph
            graph = ExecutionGraph(goal=intent, nodes={}, edges={})
            self._apply_patch(patch, graph)
            
            # 4. Execute entire graph
            return await self.runtime.execute_graph(graph)
        
        # Should not reach here, but handle gracefully
        logger.error(f"Failed to plan valid DAG after {max_planning_attempts} attempts")
        from app.avatar.runtime.graph.models.execution_graph import GraphStatus
        graph = ExecutionGraph(goal=intent, nodes={}, edges={})
        graph.status = GraphStatus.FAILED
        return self._make_error_result(
            graph,
            error_message=f"Failed to plan valid DAG after {max_planning_attempts} attempts"
        )
    
    def _apply_patch(
        self,
        patch: 'GraphPatch',
        graph: 'ExecutionGraph',
    ) -> None:
        """
        Apply a validated patch to the graph.
        
        Requirements: 26.9
        """
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        
        for action in patch.actions:
            if action.operation == PatchOperation.ADD_NODE and action.node:
                graph.add_node(action.node)
                logger.debug(f"Added node: {action.node.id}")
            
            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                graph.add_edge(action.edge)
                logger.debug(
                    f"Added edge: {action.edge.source_node} 鈫?{action.edge.target_node}"
                )
            
            elif action.operation == PatchOperation.REMOVE_NODE and action.node_id:
                if action.node_id in graph.nodes:
                    del graph.nodes[action.node_id]
                    logger.debug(f"Removed node: {action.node_id}")
            
            elif action.operation == PatchOperation.REMOVE_EDGE and action.edge_id:
                if action.edge_id in graph.edges:
                    del graph.edges[action.edge_id]
                    logger.debug(f"Removed edge: {action.edge_id}")
            
            elif action.operation == PatchOperation.FINISH:
                logger.debug("FINISH operation in patch")
        
        logger.info(
            f"Applied patch: {len(patch.actions)} actions, "
            f"graph now has {len(graph.nodes)} nodes, {len(graph.edges)} edges"
        )
    
    def _check_planner_budget(self) -> Optional[str]:
        """
        Check if planner budget limits are exceeded.
        
        Returns:
            Error message if budget exceeded, None otherwise
            
        Requirements: 26.10, 26.11, 26.12, 26.13
        """
        # Check token limit (Requirement 26.11)
        if self.max_planner_tokens and self._planner_usage['total_tokens'] >= self.max_planner_tokens:
            return (
                f"Token limit exceeded: {self._planner_usage['total_tokens']} >= "
                f"{self.max_planner_tokens}"
            )
        
        # Check call limit (Requirement 26.12)
        if self.max_planner_calls and self._planner_usage['total_calls'] >= self.max_planner_calls:
            return (
                f"Call limit exceeded: {self._planner_usage['total_calls']} >= "
                f"{self.max_planner_calls}"
            )
        
        # Check cost limit (Requirement 26.13)
        if self.max_planner_cost and self._planner_usage['total_cost'] >= self.max_planner_cost:
            return (
                f"Cost limit exceeded: ${self._planner_usage['total_cost']:.4f} >= "
                f"${self.max_planner_cost:.4f}"
            )
        
        return None
    
    def _track_planner_usage(self, patch: 'GraphPatch') -> None:
        """
        Track planner usage from patch metadata.
        
        Args:
            patch: GraphPatch with usage metadata
            
        Requirements: 26.6, 26.10
        """
        # Extract usage from patch metadata
        metadata = patch.metadata or {}
        
        tokens = metadata.get('tokens_used', 0)
        cost = metadata.get('cost', 0.0)
        
        # Update totals
        self._planner_usage['total_tokens'] += tokens
        self._planner_usage['total_calls'] += 1
        self._planner_usage['total_cost'] += cost
        
        logger.debug(
            f"Planner usage updated: "
            f"tokens={self._planner_usage['total_tokens']}, "
            f"calls={self._planner_usage['total_calls']}, "
            f"cost=${self._planner_usage['total_cost']:.4f}"
        )
    
    def get_planner_usage(self) -> Dict[str, Any]:
        """
        Get current planner usage statistics.
        
        Returns:
            Dictionary with usage statistics
            
        Requirements: 26.6
        """
        return self._planner_usage.copy()
    
    def _auto_repair_dag(self, patch: 'GraphPatch') -> Dict[str, Any]:
        """
        Auto-repair simple errors in DAG patch.
        
        Fixes:
        - Duplicate node IDs (rename duplicates)
        - Invalid field references (remove invalid edges)
        - Missing edges (no auto-fix, just log)
        
        Args:
            patch: GraphPatch to repair
            
        Returns:
            Dictionary with:
                - repaired: bool (whether repairs were made)
                - repairs: List[str] (descriptions of repairs)
                - patch: GraphPatch (repaired patch)
                
        Requirements: 20.5, 20.6, 20.7
        """
        from app.avatar.runtime.graph.models.graph_patch import PatchOperation
        
        repairs = []
        repaired = False
        
        # Track node IDs to detect duplicates
        node_ids = set()
        node_id_counter = {}
        
        # Track node output fields for validation
        node_outputs = {}
        
        new_actions = []
        
        for action in patch.actions:
            # Fix duplicate node IDs (Requirement 20.5)
            if action.operation == PatchOperation.ADD_NODE and action.node:
                original_id = action.node.id
                
                if original_id in node_ids:
                    # Duplicate found, rename
                    if original_id not in node_id_counter:
                        node_id_counter[original_id] = 1
                    node_id_counter[original_id] += 1
                    
                    new_id = f"{original_id}_{node_id_counter[original_id]}"
                    action.node.id = new_id
                    
                    repairs.append(f"Renamed duplicate node '{original_id}' to '{new_id}'")
                    repaired = True
                
                node_ids.add(action.node.id)
                
                # Track output fields (assume 'output' field exists)
                node_outputs[action.node.id] = ['output']  # Simplified
                
                new_actions.append(action)
            
            # Validate and fix invalid field references (Requirement 20.6)
            elif action.operation == PatchOperation.ADD_EDGE and action.edge:
                source_node = action.edge.source_node
                source_field = action.edge.source_field
                target_node = action.edge.target_node
                
                # Check if source node exists
                if source_node not in node_ids:
                    repairs.append(
                        f"Removed edge with invalid source node '{source_node}' "
                        f"(target: {target_node})"
                    )
                    repaired = True
                    continue  # Skip this edge
                
                # Check if target node exists
                if target_node not in node_ids:
                    repairs.append(
                        f"Removed edge with invalid target node '{target_node}' "
                        f"(source: {source_node})"
                    )
                    repaired = True
                    continue  # Skip this edge
                
                # Check if source field exists (simplified check)
                # In real implementation, would check against actual node output schema
                if source_field not in node_outputs.get(source_node, []):
                    # Try to fix by using 'output' field
                    if 'output' in node_outputs.get(source_node, []):
                        action.edge.source_field = 'output'
                        repairs.append(
                            f"Fixed invalid field reference '{source_field}' to 'output' "
                            f"for edge {source_node} → {target_node}"
                        )
                        repaired = True
                    else:
                        repairs.append(
                            f"Removed edge with invalid source field '{source_field}' "
                            f"from node '{source_node}'"
                        )
                        repaired = True
                        continue  # Skip this edge
                
                new_actions.append(action)
            
            else:
                # Keep other actions as-is
                new_actions.append(action)
        
        # Log repairs (Requirement 20.7)
        if repaired:
            logger.info(f"Auto-repaired DAG patch: {len(repairs)} repairs made")
            for repair in repairs:
                logger.debug(f"  - {repair}")
        
        # Create repaired patch
        from app.avatar.runtime.graph.models.graph_patch import GraphPatch
        repaired_patch = GraphPatch(
            actions=new_actions,
            reasoning=patch.reasoning,
            metadata=patch.metadata,
        )
        
        return {
            'repaired': repaired,
            'repairs': repairs,
            'patch': repaired_patch,
        }
    
    async def _invoke_planner_for_repair(
        self,
        graph: 'ExecutionGraph',
        failed_node_id: str,
        error_message: str,
        env_context: Dict[str, Any],
        recovery_attempts: Dict[str, int],
    ) -> Optional['GraphPatch']:
        """
        Invoke planner for error recovery.
        
        This method:
        1. Checks recovery attempt limit (max 3 per node)
        2. Calls planner.plan_repair() with failure context
        3. Returns recovery patch or None if limit exceeded
        
        Args:
            graph: Current ExecutionGraph
            failed_node_id: ID of the failed node
            error_message: Error message from the failure
            env_context: Environment context
            recovery_attempts: Dictionary tracking recovery attempts per node
            
        Returns:
            GraphPatch with recovery actions, or None if limit exceeded
            
        Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7
        """
        # Check recovery attempt limit (Requirement 10.6)
        current_attempts = recovery_attempts.get(failed_node_id, 0)
        max_recovery_attempts = 3
        
        if current_attempts >= max_recovery_attempts:
            logger.error(
                f"Recovery attempt limit exceeded for node {failed_node_id}: "
                f"{current_attempts} >= {max_recovery_attempts}"
            )
            return None
        
        # Increment recovery attempts
        recovery_attempts[failed_node_id] = current_attempts + 1
        
        logger.info(
            f"Invoking planner for repair of node {failed_node_id} "
            f"(attempt {current_attempts + 1}/{max_recovery_attempts})"
        )
        
        try:
            # Call planner with failure context (Requirements 10.1, 10.2, 10.3)
            recovery_patch = await self.planner.plan_repair(
                graph,
                failed_node_id,
                error_message,
                env_context,
            )
            
            logger.info(
                f"Planner generated recovery patch with {len(recovery_patch.actions)} actions"
            )
            
            return recovery_patch
            
        except Exception as e:
            logger.error(
                f"Planner repair invocation failed for node {failed_node_id}: {e}",
                exc_info=True
            )
            return None

    # -------------------------------------------------------------------------
    # Goal Completion Tracking (Framework-level, zero LLM calls)
    # -------------------------------------------------------------------------

    # Connectors used to split a goal into sub-goals.
    # Only split on explicit multi-goal connectors (骞朵笖/鐒跺悗/and then/etc.).
    # Bare commas/semicolons are NOT treated as sub-goal separators because they
    # often appear within a single compound task (e.g. "璇诲彇test.txt锛屾壘鍒版渶澶х殑鏁?).
    _GOAL_SPLIT_PATTERN = re.compile(
        r'\s+(?:并且?|然后|接着|之后|and then|then also|after that|additionally)\s+',
        re.IGNORECASE,
    )

    # Skills that have no IO side-effects; successful execution covers any non-IO sub-goal
    _COMPUTE_SKILLS: set = {"python.run", "python.eval", "shell.run"}

    # Keywords that indicate an IO sub-goal; these require an explicit IO skill to cover
    _IO_KEYWORDS: set = {
        "保存", "写入", "写到", "存储", "save", "write", "保存到",
        "读取", "下载", "发送", "上传", "fetch", "download", "send", "upload",
    }

    # Skill → semantic tags: what "kind of work" does this skill cover
    _SKILL_TAGS: Dict[str, List[str]] = {
        "fs.write":          ["save", "write", "file", "保存", "写入", "文件", "存储"],
        "fs.read":           ["read", "open", "load", "读取", "打开"],
        "fs.list":           ["list", "ls", "dir", "列出", "目录"],
        "fs.delete":         ["delete", "remove", "删除"],
        "fs.copy":           ["copy", "复制"],
        "fs.move":           ["move", "rename", "移动", "重命名"],
        "python.run":        ["run", "execute", "compute", "calculate", "generate", "运行", "执行", "计算", "生成"],
        "net.get":           ["fetch", "get", "download", "request", "获取", "下载", "请求"],
        "net.post":          ["post", "send", "submit", "发送", "提交"],
        "browser.open":      ["open", "browse", "visit", "打开", "浏览", "访问"],
        "computer.app.launch": ["launch", "open", "start", "启动", "打开"],
        "memory.store":      ["remember", "store", "记住", "存储"],
        "memory.retrieve":   ["recall", "retrieve", "remember", "回忆", "检索"],
    }

    def _decompose_goal(self, goal: str) -> List[str]:
        """
        Split a goal string into sub-goals using punctuation and connectors.
        Returns a list of non-empty stripped sub-goal strings.
        Single-clause goals return a list with one element.
        """
        parts = self._GOAL_SPLIT_PATTERN.split(goal)
        sub_goals = [p.strip() for p in parts if p and p.strip()]
        # Only treat as multi-goal if we actually split into 2+
        return sub_goals if len(sub_goals) > 1 else [goal]

    def _emit_plan_generated(self, graph: 'ExecutionGraph', env_context: Dict[str, Any]) -> None:
        """patch apply 后实时向前端发 plan.generated，让进度条显示步骤列表"""
        if not self.runtime.event_bus:
            return
        try:
            from app.avatar.runtime.events.types import Event, EventType
            nodes = list(graph.nodes.values())
            steps = [
                {
                    "id": str(n.id),
                    "skill": n.capability_name,
                    "skill_name": n.capability_name,
                    "description": n.capability_name.replace(".", " → "),
                    "status": "pending",
                    "order": i,
                    "params": n.params or {},
                    "depends_on": [],
                }
                for i, n in enumerate(nodes)
            ]
            event = Event(
                type=EventType.PLAN_GENERATED,
                source="graph_controller",
                payload={
                    "session_id": env_context.get("session_id", ""),
                    "plan": {
                        "id": graph.id,
                        "goal": graph.goal,
                        "steps": steps,
                    },
                },
            )
            self.runtime.event_bus.publish(event)
        except Exception as e:
            logger.warning(f"[GraphController] Failed to emit plan.generated: {e}")

    def _get_uncovered_sub_goals(
        self,
        sub_goals: List[str],
        graph: 'ExecutionGraph',
    ) -> List[str]:
        """
        Return sub-goals that have no corresponding successful node in the graph.

        Matching logic (no LLM):
        1. Collect all successful nodes' skill names + stdout/output text.
        2. For each sub-goal, check if any successful node's skill tags OR
           output text contains keywords from the sub-goal.
        3. A sub-goal is "covered" if at least one successful node matches.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        if len(sub_goals) <= 1:
            # Single-goal tasks: trust the LLM's FINISH decision
            return []

        # Build a corpus of (skill_name, output_text) for successful nodes
        successful_nodes = [
            n for n in graph.nodes.values()
            if n.status == NodeStatus.SUCCESS
        ]

        if not successful_nodes:
            # Nothing succeeded yet — all sub-goals uncovered
            return list(sub_goals)

        # IO-type keywords: sub-goals containing these require explicit IO skill coverage

        def _node_covers(node, sub_goal: str) -> bool:
            sub_goal_lower = sub_goal.lower()

            # 1. Check skill semantic tags
            skill = node.capability_name
            tags = self._SKILL_TAGS.get(skill, [skill])
            if any(tag.lower() in sub_goal_lower for tag in tags):
                return True

            # 2. Compute-only skills cover any non-IO sub-goal on success
            if skill in self._COMPUTE_SKILLS:
                if not any(kw in sub_goal_lower for kw in self._IO_KEYWORDS):
                    return True

            # 3. Check if CJK keywords from sub-goal appear in node outputs
            #    (CJK-only to avoid false positives from code tokens)
            output_text = ""
            outputs = node.outputs or {}
            for v in outputs.values():
                if isinstance(v, str):
                    output_text += v.lower()
                elif isinstance(v, dict):
                    output_text += str(v).lower()

            cjk_words = re.findall(r'[\u4e00-\u9fff]{2,}', sub_goal_lower)
            if cjk_words and any(w in output_text for w in cjk_words):
                return True

            return False

        uncovered = []
        for sub_goal in sub_goals:
            if not any(_node_covers(n, sub_goal) for n in successful_nodes):
                uncovered.append(sub_goal)

        return uncovered


