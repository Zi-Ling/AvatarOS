"""
GraphExecutor - Node Execution with Parameter Resolution

Slim orchestrator that coordinates mixin modules:
- CodeInjectorMixin: upstream node output injection into code
- PathSanitizerMixin: host→container path sanitization
- ParameterResolverMixin: DataEdge parameter resolution
- OutputProcessorMixin: output contract, schema, artifact processing
- SkillExecutorMixin: skill registry execution and LLM usage tracking

Requirements: 5.1, 5.2, 5.3, 5.7, 5.8, 7.2, 7.5, 7.6, 7.7
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import json
import logging
from datetime import datetime
from pathlib import Path

from app.core.workspace.manager import get_current_workspace
from app.avatar.runtime.graph.models.output_contract import (
    OutputContractAdapter,
    OutputCompatMode,
)

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
    from app.avatar.runtime.artifact.registry import ArtifactRegistry
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore

ARTIFACT_SIZE_THRESHOLD = 1 * 1024 * 1024

logger = logging.getLogger(__name__)


# Re-export error classes for backward compatibility
from app.avatar.runtime.graph.executor.skill_executor import ExecutionError
from app.avatar.runtime.graph.executor.parameter_resolver import (
    ParameterResolutionError,
    TransformerError,
)

from app.avatar.runtime.graph.executor.code_injector import CodeInjectorMixin
from app.avatar.runtime.graph.executor.path_sanitizer import PathSanitizerMixin
from app.avatar.runtime.graph.executor.parameter_resolver import ParameterResolverMixin
from app.avatar.runtime.graph.executor.output_processor import OutputProcessorMixin
from app.avatar.runtime.graph.executor.skill_executor import SkillExecutorMixin


class GraphExecutor(
    CodeInjectorMixin,
    PathSanitizerMixin,
    ParameterResolverMixin,
    OutputProcessorMixin,
    SkillExecutorMixin,
):
    """
    Executor for graph nodes with parameter resolution via DataEdge traversal.
    Uses skill_registry directly — no capability_registry dependency.

    Functionality is provided by mixin classes:
    - CodeInjectorMixin: _inject_node_outputs_into_code, _output_helper_code, etc.
    - PathSanitizerMixin: _build_host_path_mappings, _sanitize_code_host_paths, etc.
    - ParameterResolverMixin: _resolve_parameters, _resolve_single_edge, etc.
    - OutputProcessorMixin: _process_output_contract, _write_output_schema, etc.
    - SkillExecutorMixin: _execute_skill, _execute_sequential
    """

    def __init__(
        self,
        transformer_registry: Optional[Dict[str, Any]] = None,
        artifact_store: Optional['ArtifactStore'] = None,
        granted_permissions: Optional[List[str]] = None,
        base_path: Optional[Any] = None,
        workspace_manager: Optional[Any] = None,  # deprecated, kept for backward compat
        memory_manager: Optional[Any] = None,
        learning_manager: Optional[Any] = None,
        workspace: Optional[Any] = None,
        # Legacy params kept for backward compat
        capability_registry: Optional[Any] = None,
        type_registry: Optional[Any] = None,
        # P0: TypedOutputContract integration
        artifact_registry: Optional['ArtifactRegistry'] = None,
        trace_store: Optional['StepTraceStore'] = None,
        output_compat_mode: OutputCompatMode = OutputCompatMode.COMPATIBLE,
        # P2: PolicyEngine integration
        policy_engine: Optional[Any] = None,
        # P2: BudgetAccount integration
        budget_account: Optional[Any] = None,
    ):
        self.transformer_registry = transformer_registry or {}
        self.artifact_store = artifact_store
        self.granted_permissions: List[str] = granted_permissions or []
        self._fallback_base_path = Path(base_path) if base_path else Path(".")
        self.memory_manager = memory_manager
        self.learning_manager = learning_manager
        self.workspace = workspace
        self.artifact_registry = artifact_registry
        self.trace_store = trace_store
        self.output_compat_mode = output_compat_mode
        self._output_contract_adapter = OutputContractAdapter()
        self.policy_engine = policy_engine
        self.budget_account = budget_account

    @property
    def base_path(self) -> Path:
        """当前生效的 workspace 路径（动态，随 WorkspaceManager 切换而变化）。"""
        return self._get_base_path()

    def _get_base_path(self) -> Path:
        """获取当前 user workspace 路径。

        优先级：
          1. WorkspaceManager.get_current_workspace() — 用户可随时切换，动态生效
          2. self._fallback_base_path — 构造时传入的启动默认值（兜底）

        Task 2 的旧实现优先返回 _fallback_base_path，导致用户切换 workspace 后
        fs.write 仍写入启动时的 config.avatar_workspace（server/workspace/）。
        """
        try:
            ws = get_current_workspace()
            if ws is not None and str(ws) != ".":
                return ws
        except Exception as e:
            logger.warning(f"[GraphExecutor] get_current_workspace() failed: {e}")
        if self._fallback_base_path is not None and str(self._fallback_base_path) != ".":
            return self._fallback_base_path
        return Path.cwd()

    async def execute_node(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: Optional['ExecutionContext'] = None,
    ) -> None:
        logger.info(f"[GraphExecutor] Executing node {node.id} (skill: {node.capability_name})")
        start_time = datetime.now()

        try:
            node.mark_running()

            # P2: PolicyEngine check before execution
            if self.policy_engine is not None:
                _ctx_session_id = ""
                _ctx_task_id = ""
                if context:
                    _ctx_session_id = (
                        (context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None)
                        or getattr(getattr(context, "identity", None), "session_id", None)
                        or ""
                    )
                    _ctx_task_id = (
                        getattr(context, "task_id", None)
                        or getattr(getattr(context, "identity", None), "task_id", None)
                        or ""
                    )
                ctx_for_policy = {
                    "session_id": _ctx_session_id,
                    "task_id": _ctx_task_id,
                    "step_id": str(node.id),
                    "target_path": (node.params or {}).get("path") or (node.params or {}).get("target_path"),
                }
                decision, matched_rule = self.policy_engine.evaluate(
                    skill_name=node.capability_name,
                    params=node.params or {},
                    context=ctx_for_policy,
                )
                from app.avatar.runtime.policy.policy_engine import PolicyDecision
                if decision == PolicyDecision.DENY:
                    reason = matched_rule.reason if matched_rule else "policy denied"
                    if self.trace_store and context:
                        self.trace_store.record_event(
                            session_id=_ctx_session_id,
                            task_id=_ctx_task_id,
                            step_id=str(node.id),
                            event_type="policy_denied",
                            payload={"skill": node.capability_name, "reason": reason, "rule_id": matched_rule.rule_id if matched_rule else ""},
                        )
                    raise ExecutionError(f"Policy denied: {reason}", retryable=False)
                elif decision == PolicyDecision.REQUIRE_APPROVAL:
                    reason = matched_rule.reason if matched_rule else "approval required"
                    if self.trace_store and context:
                        self.trace_store.record_event(
                            session_id=_ctx_session_id,
                            task_id=_ctx_task_id,
                            step_id=str(node.id),
                            event_type="policy_approval_required",
                            payload={"skill": node.capability_name, "reason": reason},
                        )
                    raise ExecutionError(f"Approval required: {reason}", retryable=False)

            resolved_params = self._resolve_parameters(graph, node, context)
            final_params = {**node.params, **resolved_params}

            # Proactive coercion: LLM tool calls sometimes return nested
            # structures (list/dict) as stringified Python repr or JSON.
            # Coerce them before Pydantic validation to avoid unnecessary retries.
            final_params = self._coerce_string_params(final_params)

            # Schema-aware unwrap: if a param value is a dict but the skill
            # schema expects a list, try to extract the list from the dict.
            final_params = self._schema_aware_unwrap(node.capability_name, final_params)

            # Replace LLM-generated template variables like {{workspace_path}}
            # with the actual container mount path /workspace.
            final_params = self._replace_template_vars_in_params(final_params)

            # Safety net: detect unresolved node-reference templates like
            # {{n1.output}} which indicate a missing DataEdge (e.g. removed
            # by dag_repair due to action ordering).  Fail early with a clear
            # message instead of passing the raw template to Pydantic.
            import re as _re_tpl
            for _pk, _pv in final_params.items():
                if isinstance(_pv, str) and _re_tpl.search(r'\{\{\s*n\d+\.', _pv):
                    raise ExecutionError(
                        f"Unresolved node reference in param '{_pk}': {_pv!r}. "
                        f"This usually means the DAG is missing an edge from the "
                        f"upstream node. Check planner output and dag_repair logs.",
                        retryable=True,
                    )

            # Auto-inject search results into text-answer skill context
            # When Planner calls a text-answer skill after a search skill but doesn't pass
            # context (or can't due to token limits), we inject it automatically.
            _is_answer_skill = False
            try:
                from app.avatar.skills.registry import skill_registry as _sr
                _is_answer_skill = _sr.is_answer_skill(node.capability_name)
            except Exception:
                pass
            if _is_answer_skill and not final_params.get("context"):
                _search_context = self._find_search_results(graph)
                if _search_context:
                    final_params["context"] = _search_context

            # P1: Write SkillInputSchema to node metadata
            self._write_input_schema(node)

            outputs = await self._execute_skill(node.capability_name, final_params, context)

            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()

            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency

            if context:
                current_cost = context.variables.get("accumulated_cost", 0.0)
                context.variables.set("accumulated_cost", current_cost)

            if outputs.get("success") is False:
                msg = outputs.get("message") or outputs.get("error") or "Skill returned success=false"
                skill_retryable = outputs.get("retryable")
                if skill_retryable is not None:
                    retryable = bool(skill_retryable)
                else:
                    status_code = outputs.get("status_code")
                    if isinstance(status_code, int) and 400 <= status_code < 500:
                        retryable = False
                    else:
                        stderr = outputs.get("stderr") or outputs.get("output") or ""
                        _ENV_ERROR_PATTERNS = (
                            "ModuleNotFoundError", "ImportError", "SyntaxError",
                            "IndentationError", "No such file or directory",
                            "FileNotFoundError", "AttributeError", "TypeError",
                            "KeyError", "ValueError", "NameError", "IndexError",
                            "ZeroDivisionError", "UnboundLocalError",
                            "JSONDecodeError", "UnicodeDecodeError",
                            "PermissionError", "StopIteration",
                        )
                        retryable = not any(pat in stderr for pat in _ENV_ERROR_PATTERNS)
                raise ExecutionError(msg, retryable=retryable)

            if self.artifact_store:
                outputs = await self._offload_large_outputs(outputs, node.id, context)

            if context:
                context.set_node_output(node.id, outputs)
            node.mark_success(outputs)

            # P2: BudgetAccount — record skill cost after successful execution
            if self.budget_account is not None and context:
                try:
                    from app.avatar.runtime.policy.budget_account import CostRecord
                    _ba_session_id = (
                        getattr(context, "session_id", None)
                        or getattr(getattr(context, "identity", None), "session_id", None)
                        or ""
                    )
                    _ba_task_id = (
                        getattr(context, "task_id", None)
                        or getattr(getattr(context, "identity", None), "task_id", None)
                        or ""
                    )
                    skill_cost = float(outputs.get("cost", 0.0) or 0.0)
                    llm_cost = float(outputs.get("llm_cost", 0.0) or 0.0)
                    token_count = int(outputs.get("token_count", 0) or 0)
                    cost_rec = CostRecord(
                        step_id=str(node.id),
                        task_id=_ba_task_id,
                        session_id=_ba_session_id,
                        skill_cost=skill_cost,
                        llm_cost=llm_cost,
                        token_count=token_count,
                        model=outputs.get("model", ""),
                    )
                    self.budget_account.record_cost(cost_rec)
                except Exception as _be:
                    logger.warning(f"[GraphExecutor] BudgetAccount record_cost failed: {_be}")

            # P0: TypedOutputContract integration
            await self._process_output_contract(node, outputs, context)

            # P1: Write StepOutputSchema to node metadata
            self._write_output_schema(node, outputs)

            # P1-4: Extract artifact semantic metadata
            _host_ws = str(self.base_path)
            _session_root = str(context.workspace.root) if context and getattr(context, "workspace", None) else None
            self._extract_artifact_semantic(node, outputs, host_workspace=_host_ws, session_root=_session_root)

            logger.info(f"[GraphExecutor] Node {node.id} completed in {latency:.3f}s")

        except Exception as e:
            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()
            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency
            logger.error(f"[GraphExecutor] Node {node.id} failed: {e}", exc_info=True)
            raise

    @staticmethod
    def _find_search_results(graph: 'ExecutionGraph') -> Optional[str]:
        """Find the most recent successful search skill output in the graph.

        Uses tag-based matching (tags containing "search") instead of
        hardcoded skill names.
        """
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        _search_tags = None  # use registry centralized tags
        for node in reversed(list(graph.nodes.values())):
            if node.status != NodeStatus.SUCCESS:
                continue
            try:
                from app.avatar.skills.registry import skill_registry as _sr
                if not _sr.is_search_skill(node.capability_name):
                    continue
            except Exception:
                continue
            outputs = node.outputs or {}
            text = outputs.get("output") or ""
            if isinstance(text, str) and len(text) > 20:
                return text
        return None

    async def _offload_large_outputs(
        self,
        outputs: Dict[str, Any],
        node_id: str,
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        from app.avatar.runtime.graph.storage.artifact_store import ArtifactType

        result = {}
        for field, value in outputs.items():
            try:
                serialized = json.dumps(value, default=str).encode("utf-8")
                if len(serialized) > ARTIFACT_SIZE_THRESHOLD:
                    artifact = await self.artifact_store.store(
                        data=serialized,
                        artifact_type=ArtifactType.DATASET,
                        created_by_node=node_id,
                        metadata={"field": field, "original_type": type(value).__name__},
                    )
                    result[field] = {"__artifact_id__": artifact.id}
                    if context:
                        context.set_artifact(artifact.id, artifact.model_dump())
                else:
                    result[field] = value
            except Exception as e:
                logger.warning(f"[GraphExecutor] Failed to check/offload field '{field}': {e}")
                result[field] = value

        return result
