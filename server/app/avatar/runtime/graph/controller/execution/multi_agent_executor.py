"""
MultiAgentExecutorMixin – multi-agent orchestration mode extracted from
GraphController.

Contains:
- _parse_worker_feedback()  (module-level)
- _strip_feedback_tag()     (module-level)
- MultiAgentExecutorMixin   (class with methods mixed into GraphController)

Mixed back into GraphController via multiple inheritance.
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
    from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph, SubtaskNode

logger = logging.getLogger(__name__)


# ── Feedback parser for worker-generated feedback blocks ────────────

def _parse_worker_feedback(
    summary: str,
    tag: str,
) -> Optional[Dict[str, Any]]:
    """Extract structured feedback JSON from worker output.

    Looks for <tag> ... </tag> delimiters in the summary text.
    Returns parsed dict or None if not found / invalid.
    """
    import json as _json
    import re as _re

    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    pattern = _re.compile(
        _re.escape(open_tag) + r"\s*(.*?)\s*" + _re.escape(close_tag),
        _re.DOTALL,
    )
    match = pattern.search(summary)
    if not match:
        return None
    try:
        fb = _json.loads(match.group(1))
        if isinstance(fb, dict):
            # Normalise action to uppercase
            if "action" in fb:
                fb["action"] = str(fb["action"]).upper().strip()
                if fb["action"] == "NONE":
                    fb["action"] = ""
            return fb
    except (_json.JSONDecodeError, TypeError, ValueError):
        logger.debug("[FeedbackParser] Failed to parse feedback JSON from worker output")
    return None


def _strip_feedback_tag(summary: str, tag: str) -> str:
    """Remove the <tag>...</tag> feedback block from worker output.

    Returns the summary with the feedback block stripped so it doesn't
    leak into user-visible text.
    """
    import re as _re

    open_tag = f"<{tag}>"
    close_tag = f"</{tag}>"
    pattern = _re.compile(
        r"\s*" + _re.escape(open_tag) + r".*?" + _re.escape(close_tag) + r"\s*",
        _re.DOTALL,
    )
    return pattern.sub("", summary).strip()


# ── Mixin class ─────────────────────────────────────────────────────

class MultiAgentExecutorMixin:
    """Multi-agent orchestration mode for GraphController."""

    def _dispatch_to_role(self, node_type: str) -> str:
        """根据节点类型分派给对应角色. 使用 MultiAgentConfig."""
        from app.avatar.runtime.multiagent.config import MultiAgentConfig
        _cfg = getattr(self, '_multi_agent_config', None) or MultiAgentConfig()
        return _cfg.role_dispatch_table.get(node_type, _cfg.default_role)

    async def _execute_multi_agent_mode(
        self,
        intent: str,
        env_context: Dict[str, Any],
        config: Dict[str, Any],
    ) -> 'ExecutionResult':
        """多 Agent 编排执行模式 — 委托给 SupervisorRuntime dispatch loop.

        流程:
        1. 组装 Supervisor 依赖
        2. 复杂度评估（低复杂度回退 react）
        3. LLM 分解意图 → SubtaskGraph
        4. GraphValidator 校验 DAG
        5. SupervisorRuntime.run() — 连续 dispatch loop
        6. 合并结果
        """
        import time as _time
        from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph, GraphStatus
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult

        _start_mono = _time.monotonic()

        # ── Structured logging: set trace context ───────────────────────
        try:
            from app.log.structured import set_trace_context
            set_trace_context(
                trace_id=env_context.get("trace_id", ""),
                session_id=env_context.get("session_id", ""),
                task_id=env_context.get("task_id", ""),
            )
        except Exception:
            pass

        # ── Parent session lifecycle ────────────────────────────────────
        from app.avatar.runtime.graph.lifecycle.execution_lifecycle import ExecutionLifecycle
        _lifecycle: Optional[ExecutionLifecycle] = None
        _session_id = env_context.get("session_id", "")
        try:
            from app.services.session_store import ExecutionSessionStore
            _workspace_path = env_context.get("workspace_path") or (
                str(self.guard.config.workspace_root)
                if self.guard and self.guard.config.workspace_root else ""
            )
            _exec_session = ExecutionSessionStore.create(
                goal=intent,
                run_id=env_context.get("run_id"),
                task_id=env_context.get("task_id"),
                request_id=env_context.get("request_id"),
                trace_id=env_context.get("trace_id"),
                conversation_id=_session_id,
                workspace_path=_workspace_path,
            )
            _lifecycle = ExecutionLifecycle(_exec_session.id)
            await _lifecycle.on_session_start()
        except Exception as _lc_err:
            logger.warning("[MultiAgent] parent lifecycle setup failed: %s", _lc_err)

        try:
            from app.avatar.runtime.multiagent.core.supervisor import (
                Supervisor, GraphValidator, TerminationEvaluator, InstanceManager,
            )
            from app.avatar.runtime.multiagent.roles.spawn_policy import SpawnPolicy
            from app.avatar.runtime.multiagent.roles.role_spec import RoleSpecRegistry
            from app.avatar.runtime.multiagent.persistence.artifact import ArtifactStore
            from app.avatar.runtime.multiagent.observability.trace_integration import TraceIntegration
            from app.avatar.runtime.multiagent.core.subtask_graph import (
                SubtaskGraph, SubtaskNode, SubtaskEdge,
            )
            from app.avatar.runtime.multiagent.config import MultiAgentConfig
            from app.avatar.runtime.multiagent.roles.role_runners import get_role_runner
            from app.avatar.runtime.multiagent.core.supervisor_runtime import (
                SupervisorRuntime, TaskResult,
            )

            _ma_cfg = getattr(self, '_multi_agent_config', None) or MultiAgentConfig()

            # ── 1. 组装依赖 ──
            _kernel_registry = getattr(self, '_multi_agent_registry', None)
            _kernel_spawn_policy = getattr(self, '_multi_agent_spawn_policy', None)
            _kernel_artifact_store = getattr(self, '_multi_agent_artifact_store', None)

            role_registry = _kernel_registry if _kernel_registry is not None else RoleSpecRegistry()
            spawn_policy = _kernel_spawn_policy if _kernel_spawn_policy is not None else SpawnPolicy()
            artifact_store = _kernel_artifact_store if _kernel_artifact_store is not None else ArtifactStore()
            trace = TraceIntegration()

            supervisor = Supervisor(
                role_registry=role_registry,
                spawn_policy=spawn_policy,
                artifact_store=artifact_store,
                graph_controller=self,
                trace=trace,
                complexity_threshold=config.get("complexity_threshold", _ma_cfg.default_complexity_threshold),
                max_rounds=config.get("max_rounds", _ma_cfg.default_max_rounds),
                timeout_seconds=config.get("timeout_seconds", _ma_cfg.default_timeout_seconds),
            )

            graph_validator = GraphValidator(role_registry=role_registry)
            instance_manager = InstanceManager(
                spawn_policy=spawn_policy,
                role_registry=role_registry,
            )

            # ── 2. 直接进入编排（复杂度已由 main.py 判定） ──
            trace.multi_agent_mode_decision("multi_agent", "pre-routed by AvatarMain")
            logger.info("[MultiAgent] 开始编排: %s", intent[:_ma_cfg.intent_log_preview_chars])

            # ── 2.5 Gate resume: try to restore SubtaskGraph from snapshot ──
            _restored_graph = None
            if env_context.get("_gate_resumed"):
                _task_session_id = env_context.get("task_session_id", "")
                if _task_session_id:
                    try:
                        from app.avatar.runtime.multiagent.persistence.graph_persistence import load_subtask_graph
                        _snapshot = load_subtask_graph(_task_session_id)
                        if _snapshot and _snapshot["graph"].nodes:
                            _restored_graph = _snapshot["graph"]
                            logger.info(
                                "[MultiAgent] Restored SubtaskGraph from snapshot: %d nodes",
                                len(_restored_graph.nodes),
                            )
                    except Exception as _restore_err:
                        logger.debug("[MultiAgent] Graph restore failed: %s", _restore_err)

            # ── 3. LLM 分解意图 → SubtaskGraph ──
            if _restored_graph is not None:
                subtask_graph = _restored_graph
            else:
                subtask_graph = await self._decompose_intent(intent, env_context)

            if not subtask_graph.nodes:
                logger.warning("[MultiAgent] Empty decomposition, falling back to react")
                return await self._execute_react_mode(intent, env_context, config)

            subtask_graph.metadata["goal"] = intent

            # Log decomposition result
            _parallel_groups = subtask_graph.get_parallel_groups()
            trace.decomposition_result(
                task_count=len(subtask_graph.nodes),
                roles=[n.responsible_role for n in subtask_graph.nodes.values()],
                parallel_layers=len(_parallel_groups),
                node_summaries=[
                    {"id": n.node_id, "role": n.responsible_role,
                     "goal": n.description[:_ma_cfg.intent_binding_max_chars]}
                    for n in subtask_graph.nodes.values()
                ],
            )

            # ── 4. Semantic validation ──
            dag_ok, dag_errors = subtask_graph.validate_dag()
            if not dag_ok:
                logger.error("[MultiAgent] DAG validation failed: %s, falling back to react", dag_errors)
                trace.validation_result(False, dag_errors)
                return await self._execute_react_mode(intent, env_context, config)

            rules_ok, rules_errors = graph_validator.validate_rules(subtask_graph)
            trace.validation_result(rules_ok, rules_errors)
            if rules_ok:
                logger.info("[MultiAgent] Graph validation passed, %d nodes", len(subtask_graph.nodes))
            else:
                logger.warning("[MultiAgent] 子任务图校验有问题: %s", rules_errors)

            # ── 4.5 Persist SubtaskGraph snapshot for gate resume / crash recovery ──
            _task_session_id = env_context.get("task_session_id", "")
            if _task_session_id:
                try:
                    from app.avatar.runtime.multiagent.persistence.graph_persistence import save_subtask_graph
                    save_subtask_graph(
                        task_session_id=_task_session_id,
                        graph=subtask_graph,
                        results={},
                        intent=intent,
                        env_context=env_context,
                        reason="pre_dispatch",
                    )
                except Exception as _snap_err:
                    logger.debug("[MultiAgent] Graph snapshot save failed: %s", _snap_err)

            # ── 5. SupervisorRuntime dispatch loop ──
            # Build the executor callback that bridges to _execute_react_mode
            # with real AgentInstance lifecycle management.
            _controller = self

            async def _subtask_executor(
                node: SubtaskNode,
                worker_instance_id: str,
                upstream_ctx: Dict[str, Any],
                all_results: Dict[str, Any],
                cfg: MultiAgentConfig,
            ) -> TaskResult:
                """Execute a subtask via _execute_react_mode with worker lifecycle."""
                # ── Result cache lookup ─────────────────────────────────
                try:
                    from app.avatar.runtime.multiagent.execution.result_cache import SubtaskResultCache
                    _cache = getattr(_controller, '_result_cache', None)
                    if _cache is None:
                        _cache = SubtaskResultCache(cfg)
                        _controller._result_cache = _cache
                    cached = _cache.get(
                        node.responsible_role, node.description, node.input_bindings,
                    )
                    if cached is not None:
                        logger.info("[MultiAgent] Cache HIT for %s", node.node_id)
                        return TaskResult(
                            node_id=node.node_id, success=True,
                            result_data=cached, execution_time=0.0,
                            worker_instance_id=worker_instance_id,
                        )
                except Exception:
                    pass

                _parent_depth = env_context.get("_execution_depth", 0)
                _child_depth = _parent_depth + 1
                _parent_budget = env_context.get(
                    "_planner_budget",
                    _controller.max_planner_invocations_per_graph,
                )
                _layer_size = max(len(subtask_graph.get_ready_nodes()), 1)

                role_runner = get_role_runner(node.responsible_role, cfg)
                _budget_multiplier = role_runner.get_budget_multiplier()
                _child_budget = max(
                    cfg.child_budget_min,
                    min(
                        cfg.child_budget_max,
                        int(_parent_budget * cfg.child_budget_ratio
                            * _budget_multiplier / _layer_size),
                    ),
                )

                sub_env = {**env_context, "upstream_results": upstream_ctx}
                sub_env["subtask_description"] = node.description
                sub_env["subtask_role"] = node.responsible_role
                sub_env["_execution_depth"] = _child_depth
                sub_env["_planner_budget"] = _child_budget
                sub_env["_worker_instance_id"] = worker_instance_id

                # Inject shared memory namespace reference
                try:
                    from app.avatar.runtime.multiagent.execution.shared_memory import get_shared_memory
                    _ns_id = env_context.get("session_id", "") or env_context.get("task_session_id", "")
                    if _ns_id:
                        _shared_mem = get_shared_memory(_ns_id, cfg)
                        sub_env["_shared_memory"] = _shared_mem
                        # Pre-load shared memory data into upstream context
                        _shared_data = _shared_mem.get_all(role=node.responsible_role)
                        if _shared_data:
                            sub_env["shared_memory_data"] = _shared_data
                except Exception:
                    pass

                subtask_spec = {
                    "expected_output": node.output_contract,
                    "input_bindings": node.input_bindings,
                    "acceptance_criteria": node.success_criteria,
                }

                sub_intent = _controller._build_subtask_intent(
                    node, intent, upstream_ctx,
                )
                sub_intent, sub_env = role_runner.configure(
                    sub_intent, sub_env, subtask_spec,
                )

                _t0 = _time.monotonic()
                try:
                    result = await _controller._execute_react_mode(
                        sub_intent, sub_env, config,
                    )
                    _elapsed = _time.monotonic() - _t0

                    result_data: Dict[str, Any] = {
                        "summary": _strip_feedback_tag(
                            result.summary or "", cfg.feedback_json_tag,
                        ) if cfg.feedback_generation_enabled else (result.summary or ""),
                        "final_status": result.final_status,
                        "role": node.responsible_role,
                    }
                    if hasattr(result, "graph") and result.graph:
                        _artifacts = []
                        _output_data = {}
                        for _n in result.graph.nodes.values():
                            _outputs = getattr(_n, "outputs", None) or {}
                            for _k, _v in _outputs.items():
                                if isinstance(_v, str) and "." in _v:
                                    _artifacts.append(_v)
                                # Capture actual output data for downstream consumption
                                _output_data[_k] = _v
                            # Also capture result text from node
                            _node_result = getattr(_n, "result", None)
                            if _node_result and isinstance(_node_result, str):
                                _output_data["_result_text"] = _node_result[:cfg.aggregation_result_text_max_chars]
                        if _artifacts:
                            result_data["artifact_paths"] = _artifacts
                        if _output_data:
                            result_data["output_data"] = _output_data

                    # ── Record per-subtask cost ─────────────────────────
                    _planner_usage = _controller.get_planner_usage()
                    _subtask_tokens = _planner_usage.get("total_tokens", 0)
                    _subtask_cost = _planner_usage.get("total_cost", 0.0)
                    result_data["cost"] = {
                        "tokens": _subtask_tokens,
                        "cost": _subtask_cost,
                        "execution_time": _elapsed,
                    }
                    # Record to BudgetAccount if available
                    _budget_account = getattr(_controller, '_budget_account', None)
                    if _budget_account is not None:
                        try:
                            from app.avatar.runtime.policy.budget_account import CostRecord as _CR
                            _budget_account.record_cost(_CR(
                                step_id=node.node_id,
                                task_id=env_context.get("task_id", ""),
                                session_id=env_context.get("session_id", ""),
                                token_count=_subtask_tokens,
                                llm_cost=_subtask_cost,
                                model=env_context.get("_model", ""),
                            ))
                        except Exception:
                            pass

                    # ── Record metrics ──────────────────────────────────
                    try:
                        from app.avatar.runtime.multiagent.observability.metrics import get_metrics
                        _m = get_metrics()
                        _m.record_subtask_execution(
                            node_id=node.node_id,
                            role=node.responsible_role,
                            duration_seconds=_elapsed,
                            success=result.success,
                        )
                        if _subtask_tokens > 0:
                            _m.record_cost(node.responsible_role, _subtask_tokens, _subtask_cost)
                    except Exception:
                        pass

                    # ── Cache write + shared memory write ───────────────
                    if result.success:
                        try:
                            if _cache is not None:
                                _cache.put(
                                    node.responsible_role, node.description,
                                    node.input_bindings, result_data,
                                )
                        except Exception:
                            pass
                        try:
                            _sm = sub_env.get("_shared_memory")
                            if _sm is not None:
                                _sm.write(
                                    f"result:{node.node_id}",
                                    result_data.get("summary", ""),
                                    role=node.responsible_role,
                                    node_id=node.node_id,
                                )
                        except Exception:
                            pass

                    return TaskResult(
                        node_id=node.node_id,
                        success=result.success,
                        result_data=result_data,
                        error_message=result.error_message or "",
                        execution_time=_elapsed,
                        worker_instance_id=worker_instance_id,
                        feedback=_parse_worker_feedback(
                            result.summary or "",
                            cfg.feedback_json_tag,
                        ) if cfg.feedback_generation_enabled else None,
                    )
                except Exception as sub_exc:
                    _elapsed = _time.monotonic() - _t0
                    return TaskResult(
                        node_id=node.node_id,
                        success=False,
                        error_message=str(sub_exc),
                        execution_time=_elapsed,
                        worker_instance_id=worker_instance_id,
                    )

            runtime = SupervisorRuntime(
                graph=subtask_graph,
                config=_ma_cfg,
                instance_manager=instance_manager,
                trace=trace,
                max_rounds=config.get("max_rounds", _ma_cfg.default_max_rounds),
                timeout_seconds=config.get("timeout_seconds", _ma_cfg.default_timeout_seconds),
                local_replanner=self._build_local_replanner(_ma_cfg),
            )

            # ── Transition parent session to running BEFORE dispatch ────
            if _lifecycle is not None:
                try:
                    await _lifecycle.on_execution_started()
                except Exception as _lc_err:
                    logger.debug("[MultiAgent] lifecycle running transition: %s", _lc_err)

            runtime_result = await runtime.run(_subtask_executor)

            # ── 5.5 Post-dispatch snapshot (with completed node states) ──
            if _task_session_id:
                try:
                    from app.avatar.runtime.multiagent.persistence.graph_persistence import save_subtask_graph
                    save_subtask_graph(
                        task_session_id=_task_session_id,
                        graph=subtask_graph,
                        results=runtime_result.subtask_results,
                        intent=intent,
                        env_context=env_context,
                        reason="post_dispatch",
                    )
                except Exception as _snap_err:
                    logger.debug("[MultiAgent] Post-dispatch snapshot save failed: %s", _snap_err)

            # ── 6. 合并结果 ──
            elapsed = _time.monotonic() - _start_mono
            all_success = runtime_result.success

            result_data = supervisor.synthesize_results(subtask_graph)

            # Aggregate subtask summaries, artifacts, output_data, and traces
            summaries = []
            all_artifact_paths: List[str] = []
            aggregated_output_data: Dict[str, Any] = {}
            for nid, data in runtime_result.subtask_results.items():
                _sub_summary = data.get("summary", "")
                if _sub_summary:
                    summaries.append(f"[{nid}] {_sub_summary}")
                _sub_artifacts = data.get("artifact_paths", [])
                if _sub_artifacts:
                    all_artifact_paths.extend(_sub_artifacts)
                # Collect output_data from each subtask for parent-level access
                _sub_output = data.get("output_data")
                if _sub_output and isinstance(_sub_output, dict):
                    if len(aggregated_output_data) < _ma_cfg.aggregation_max_subtask_outputs:
                        # Truncate large values to prevent memory bloat
                        _truncated = {}
                        for _ok, _ov in _sub_output.items():
                            _sv = str(_ov)
                            if len(_sv) > _ma_cfg.aggregation_output_max_chars:
                                _truncated[_ok] = _sv[:_ma_cfg.aggregation_output_max_chars] + "…"
                            else:
                                _truncated[_ok] = _ov
                        aggregated_output_data[nid] = _truncated
                # Record per-subtask completion in parent lifecycle
                if _lifecycle is not None:
                    try:
                        if data.get("success", True):
                            await _lifecycle.on_node_completed(nid, step_type="subtask")
                        else:
                            await _lifecycle.on_node_failed(
                                nid, error=data.get("error_message"),
                            )
                    except Exception:
                        pass
                # Record subtask trace event in parent session
                if _lifecycle is not None:
                    try:
                        _lifecycle._trace.record_session_event(
                            session_id=_lifecycle.session_id,
                            event_type="subtask_result",
                            payload={
                                "node_id": nid,
                                "success": data.get("success", False),
                                "role": data.get("role", ""),
                                "summary": _sub_summary[:_ma_cfg.intent_summary_max_chars],
                                "artifact_count": len(_sub_artifacts),
                                "has_output_data": bool(_sub_output),
                            },
                        )
                    except Exception:
                        pass

            final_summary = result_data.get("summary", "") or "\n".join(summaries)

            logger.info(
                "[MultiAgent] 编排完成: %d/%d 成功, %.1fs",
                runtime_result.completed_nodes, runtime_result.total_nodes, elapsed,
            )

            graph = ExecutionGraph(goal=intent, nodes={}, edges={})
            graph.status = GraphStatus.SUCCESS if all_success else GraphStatus.FAILED
            # Attach aggregated subtask output data to graph metadata
            if aggregated_output_data:
                graph.metadata["subtask_outputs"] = aggregated_output_data

            # Aggregate cost across all subtasks
            _total_tokens = 0
            _total_cost = 0.0
            for nid, data in runtime_result.subtask_results.items():
                _sub_cost = data.get("cost", {})
                _total_tokens += _sub_cost.get("tokens", 0)
                _total_cost += _sub_cost.get("cost", 0.0)
            if _total_tokens > 0 or _total_cost > 0:
                graph.metadata["cost_summary"] = {
                    "total_tokens": _total_tokens,
                    "total_cost": round(_total_cost, 6),
                    "subtask_count": runtime_result.total_nodes,
                }

            # ── Parent session lifecycle: terminal transition ───────────
            if _lifecycle is not None:
                _lc_status = "completed" if all_success else "failed"
                _rs = "success" if all_success else "partial_success"
                try:
                    await _lifecycle.on_session_end(
                        lifecycle_status=_lc_status,
                        result_status=_rs,
                        total_nodes=runtime_result.total_nodes,
                        completed_nodes=runtime_result.completed_nodes,
                        failed_nodes=runtime_result.failed_nodes,
                    )
                    # Record aggregation summary trace
                    _lifecycle._trace.record_session_event(
                        session_id=_lifecycle.session_id,
                        event_type="multi_agent_aggregation",
                        payload={
                            "total_subtasks": runtime_result.total_nodes,
                            "completed": runtime_result.completed_nodes,
                            "failed": runtime_result.failed_nodes,
                            "artifact_count": len(all_artifact_paths),
                            "output_data_keys": list(aggregated_output_data.keys()),
                            "terminated_reason": runtime_result.terminated_reason,
                            "elapsed_seconds": round(elapsed, 2),
                        },
                    )
                except Exception as _lc_err:
                    logger.debug("[MultiAgent] lifecycle end transition: %s", _lc_err)

            # Emit task.completed via EventBus
            try:
                from app.avatar.runtime.events.types import Event, EventType
                if self.runtime.event_bus:
                    event = Event(
                        type=EventType.TASK_COMPLETED,
                        source="graph_controller",
                        payload={
                            "session_id": env_context.get("session_id", ""),
                            "task": {
                                "id": str(graph.id),
                                "status": "FAILED" if not all_success else "SUCCESS",
                            },
                            "step_count": len(subtask_graph.nodes),
                        },
                    )
                    self.runtime.event_bus.publish(event)
            except Exception as _evt_err:
                logger.debug("[EventEmitter] multi-agent task.completed failed: %s", _evt_err)

            _exec_result = ExecutionResult(
                graph=graph,
                success=all_success,
                final_status="success" if all_success else "partial_success",
                completed_nodes=runtime_result.completed_nodes,
                failed_nodes=runtime_result.failed_nodes,
                execution_time=elapsed,
                summary=final_summary,
                artifact_paths=all_artifact_paths or None,
            )
            return _exec_result

        except Exception as exc:
            logger.error("[GraphController] multi_agent mode error: %s", exc, exc_info=True)
            # ── Parent session lifecycle: mark failed on exception ──────
            if _lifecycle is not None:
                try:
                    await _lifecycle.on_session_end(
                        lifecycle_status="failed",
                        result_status="failed",
                        error_message=str(exc),
                    )
                except Exception:
                    pass
            logger.info("[MultiAgent] 异常回退 react 模式")
            try:
                return await self._execute_react_mode(intent, env_context, config)
            except Exception as fallback_exc:
                logger.error("[MultiAgent] react 回退也失败: %s", fallback_exc)
                graph = ExecutionGraph(goal=intent, nodes={}, edges={})
                graph.status = GraphStatus.FAILED
                return self._make_error_result(graph, error_message=str(exc))

    def _build_local_replanner(self, ma_cfg: 'MultiAgentConfig') -> Optional[Any]:
        """Construct LLMLocalReplanner if an LLM client is available.

        Returns None if no LLM client is accessible (graceful degradation).
        """
        try:
            _llm = getattr(self, '_llm_client', None) or (
                getattr(self.runtime, 'llm_client', None) if self.runtime else None
            )
            if _llm is None:
                logger.debug("[MultiAgent] No LLM client available for LocalReplanner")
                return None
            from app.avatar.runtime.multiagent.resilience.local_replanner import (
                LLMLocalReplanner, LocalReplanConfig,
            )
            return LLMLocalReplanner(
                llm=_llm,
                config=LocalReplanConfig(),
                ma_config=ma_cfg,
            )
        except Exception as exc:
            logger.debug("[MultiAgent] LocalReplanner construction failed: %s", exc)
            return None

    async def _decompose_intent(
        self,
        intent: str,
        env_context: Dict[str, Any],
    ) -> 'SubtaskGraph':
        """Semantic-level task decomposition via LLM.

        Produces SubtaskNodes with:
        - goal (semantic description, not skill-level)
        - suggested_role (researcher/executor/writer)
        - expected_output (type, format, description)
        - input_bindings (references to upstream outputs)
        - acceptance_criteria
        - parallelizable flag → drives DAG edge construction
        """
        import json as _json
        from app.avatar.runtime.multiagent.core.subtask_graph import (
            SubtaskGraph, SubtaskNode, SubtaskEdge,
        )
        from app.avatar.runtime.multiagent.config import MultiAgentConfig

        _cfg = getattr(self, '_multi_agent_config', None) or MultiAgentConfig()

        # Build LLM prompt for semantic decomposition
        user_prompt = f"Task to decompose:\n{intent}"

        try:
            # Access the underlying LLM client via planner's interactive_planner
            _llm = self.planner.interactive_planner._llm
            from app.llm.types import LLMMessage, LLMRole
            import asyncio as _asyncio

            _messages = [
                LLMMessage(role=LLMRole.SYSTEM, content=_cfg.decompose_system_prompt),
                LLMMessage(role=LLMRole.USER, content=user_prompt),
            ]
            # BaseLLMClient.chat() is synchronous — run in executor
            loop = _asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, _llm.chat, _messages,
            )
            raw = response.content.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                elif "```" in raw:
                    raw = raw[:raw.rfind("```")]
            raw = raw.strip()

            specs = _json.loads(raw)
            if not isinstance(specs, list):
                specs = [specs]
        except Exception as plan_err:
            logger.warning("[MultiAgent] Semantic decomposition failed: %s, single-node fallback", plan_err)
            graph = SubtaskGraph()
            node = SubtaskNode(
                node_id="t_0",
                description=intent,
                responsible_role="executor",
                output_contract={"type": "data", "description": intent[:_cfg.intent_original_goal_max_chars]},
            )
            graph.nodes["t_0"] = node
            return graph

        # Build SubtaskGraph from LLM specs
        graph = SubtaskGraph()
        node_ids: list[str] = []

        for spec in specs[:_cfg.max_subtasks]:
            task_id = spec.get("task_id", f"t_{len(node_ids)}")
            goal = spec.get("goal", "")
            if not goal:
                continue

            role = spec.get("suggested_role", "executor")
            if role not in ("researcher", "executor", "writer"):
                role = "executor"

            expected_output = spec.get("expected_output", {})
            input_bindings = spec.get("input_bindings", {})
            acceptance = spec.get("acceptance_criteria", [])
            parallelizable = spec.get("parallelizable", False)
            depends_on = spec.get("depends_on", [])

            node = SubtaskNode(
                node_id=task_id,
                description=goal,
                responsible_role=role,
                input_bindings=input_bindings,
                output_contract=expected_output,
                success_criteria=acceptance,
                is_parallel=parallelizable,
            )
            graph.nodes[task_id] = node
            node_ids.append(task_id)

            # Build edges from depends_on
            for dep_id in depends_on:
                if dep_id in graph.nodes:
                    graph.edges.append(SubtaskEdge(
                        source_node_id=dep_id,
                        target_node_id=task_id,
                    ))

        # If no explicit dependencies were set, infer sequential chain
        # for non-parallelizable nodes
        if not graph.edges and len(node_ids) > 1:
            for j in range(1, len(node_ids)):
                prev_node = graph.nodes[node_ids[j - 1]]
                curr_node = graph.nodes[node_ids[j]]
                if not curr_node.is_parallel:
                    graph.edges.append(SubtaskEdge(
                        source_node_id=node_ids[j - 1],
                        target_node_id=node_ids[j],
                    ))

        logger.info(
            "[MultiAgent] Semantic decomposition: %d tasks, roles=%s",
            len(graph.nodes),
            {n.responsible_role for n in graph.nodes.values()},
        )

        # ── Output contract inheritance ─────────────────────────────
        # If the parent intent specifies file deliverables (md, txt, docx, etc.),
        # ensure the final sink node(s) inherit artifact-type output contracts.
        # This prevents the LLM from downgrading "write report.md" to "data" output.
        import re as _re
        _file_pattern = _re.compile(
            r'[\w\-]+\.(md|txt|docx|pdf|csv|json|html|xml|py|js|ts)',
            _re.IGNORECASE,
        )
        _file_matches = _file_pattern.findall(intent)
        if _file_matches:
            # Find sink nodes (no outgoing edges)
            _sources = {e.source_node_id for e in graph.edges}
            _sink_ids = [nid for nid in graph.nodes if nid not in _sources]
            if not _sink_ids:
                _sink_ids = [node_ids[-1]] if node_ids else []

            for _sink_id in _sink_ids:
                _sink = graph.nodes.get(_sink_id)
                if _sink is None:
                    continue
                _oc = _sink.output_contract or {}
                _oc_type = _oc.get("type", "")
                # Only upgrade if current type is generic (data/text/empty)
                if _oc_type in ("data", "text", ""):
                    _fmt = _file_matches[-1]  # last matched extension
                    _sink.output_contract = {
                        "type": "artifact",
                        "format": _fmt,
                        "description": _oc.get("description", _sink.description),
                    }
                    # Also upgrade role to writer if it's executor
                    if _sink.responsible_role == "executor":
                        _sink.responsible_role = "writer"
                    logger.info(
                        "[MultiAgent] Output contract inherited: %s → artifact/%s (role=%s)",
                        _sink_id, _fmt, _sink.responsible_role,
                    )

        return graph

    def _collect_upstream_results(
        self,
        node_id: str,
        subtask_graph: 'SubtaskGraph',
        subtask_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Collect structured upstream results for a downstream node.

        Returns {src_node_id: result_data} where result_data contains:
        - summary: text summary (fallback)
        - role: which role produced this
        - final_status: completed/failed
        - artifact_paths: list of produced file paths
        - output_contract: the upstream node's declared output spec
        - data_bindings: resolved input_binding values (if edge has data_mapping)

        Downstream nodes consume this via input_bindings references.
        Text summary is preserved as fallback for unstructured data.
        """
        upstream: Dict[str, Any] = {}
        for edge in subtask_graph.edges:
            if edge.target_node_id == node_id:
                src = edge.source_node_id
                if src not in subtask_results:
                    continue

                result = dict(subtask_results[src])

                # Attach the upstream node's output_contract for type checking
                src_node = subtask_graph.nodes.get(src)
                if src_node:
                    result["output_contract"] = src_node.output_contract

                # Resolve data_mapping from edge (if present)
                if edge.data_mapping:
                    result["data_bindings"] = edge.data_mapping

                upstream[src] = result
        return upstream

    def _build_subtask_intent(
        self,
        node: 'SubtaskNode',
        original_intent: str,
        upstream_results: Dict[str, Any],
    ) -> str:
        """Build subtask intent with structured upstream context."""
        from app.avatar.runtime.multiagent.config import MultiAgentConfig
        _cfg = getattr(self, '_multi_agent_config', None) or MultiAgentConfig()

        parts = [node.description]

        if upstream_results:
            ctx_lines = []
            for src_id, data in upstream_results.items():
                summary = data.get("summary", "")
                role = data.get("role", "")
                artifacts = data.get("artifact_paths", [])
                output_data = data.get("output_data", {})
                line = f"- {src_id}"
                if role:
                    line += f" ({role})"
                line += f": {summary[:_cfg.intent_summary_max_chars]}"
                if artifacts:
                    line += f" [artifacts: {', '.join(artifacts[:_cfg.intent_max_artifact_refs])}]"
                ctx_lines.append(line)

                # Include actual output data for downstream consumption
                if output_data:
                    for _ok, _ov in output_data.items():
                        if _ok.startswith("_"):
                            continue
                        _ov_str = str(_ov)[:_cfg.intent_summary_max_chars]
                        if _ov_str:
                            ctx_lines.append(f"  [{_ok}]: {_ov_str}")

            if ctx_lines:
                parts.append(f"\n\nUpstream results:\n" + "\n".join(ctx_lines))

        if node.input_bindings:
            binding_lines = []
            for name, ref in node.input_bindings.items():
                if isinstance(ref, str) and "." in ref:
                    src_id = ref.split(".", 1)[0]
                    if src_id in upstream_results:
                        binding_lines.append(
                            f"- {name}: from {src_id} "
                            f"({upstream_results[src_id].get('summary', '')[:_cfg.intent_binding_max_chars]})"
                        )
            if binding_lines:
                parts.append(f"\n\nInput bindings:\n" + "\n".join(binding_lines))

        parts.append(f"\n\n(Original task: {original_intent[:_cfg.intent_original_goal_max_chars]})")
        return "".join(parts)
