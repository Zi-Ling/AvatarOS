"""
GraphExecutor - Node Execution with Parameter Resolution

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
    TransportMode,
    ValueKind,
    ArtifactRole,
    InvalidTransportError,
)

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.models.data_edge import DataEdge
    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext
    from app.avatar.runtime.artifact.registry import ArtifactRegistry
    from app.avatar.runtime.graph.storage.step_trace_store import StepTraceStore

ARTIFACT_SIZE_THRESHOLD = 1 * 1024 * 1024

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Skill execution failure. retryable=False means no retry should be attempted."""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable

class ParameterResolutionError(ExecutionError):
    pass

class TransformerError(ExecutionError):
    pass


class GraphExecutor:
    """
    Executor for graph nodes with parameter resolution via DataEdge traversal.
    Uses skill_registry directly — no capability_registry dependency.
    """

    def __init__(
        self,
        transformer_registry: Optional[Dict[str, Any]] = None,
        artifact_store: Optional['ArtifactStore'] = None,
        granted_permissions: Optional[List[str]] = None,
        base_path: Optional[Any] = None,          # fallback，WorkspaceManager 未初始化时使用
        workspace_manager: Optional[Any] = None,  # 已废弃，保留向后兼容，不再使用
        memory_manager: Optional[Any] = None,
        learning_manager: Optional[Any] = None,
        workspace: Optional[Any] = None,          # SessionWorkspace — 传给 SkillContext.extra
        # Legacy params kept for backward compat during transition
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
        """
        获取当前 user workspace 路径。
        统一走 get_current_workspace()，workspace 切换后立即生效。
        """
        try:
            return get_current_workspace()
        except Exception as e:
            logger.warning(f"[GraphExecutor] get_current_workspace() failed: {e}")
            return self._fallback_base_path

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
                # ExecutionContext stores session_id in identity.session_id, not as a direct attr
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
                # 优先使用 skill 自己声明的 retryable（语义失败不应重试）
                skill_retryable = outputs.get("retryable")
                if skill_retryable is not None:
                    retryable = bool(skill_retryable)
                else:
                    # 4xx HTTP 错误：客户端问题，重试无意义
                    status_code = outputs.get("status_code")
                    if isinstance(status_code, int) and 400 <= status_code < 500:
                        retryable = False
                    else:
                        # 环境错误（缺包、语法错误等）：确定性失败，重试无意义
                        stderr = outputs.get("stderr") or outputs.get("output") or ""
                        _ENV_ERROR_PATTERNS = (
                            "ModuleNotFoundError",
                            "ImportError",
                            "SyntaxError",
                            "IndentationError",
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

            logger.info(f"[GraphExecutor] Node {node.id} completed in {latency:.3f}s")

        except Exception as e:
            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()
            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency
            logger.error(f"[GraphExecutor] Node {node.id} failed: {e}", exc_info=True)
            raise  # 让 NodeRunner 的 retry 逻辑接管

    async def _process_output_contract(
        self,
        node: 'StepNode',
        outputs: Dict[str, Any],
        context: Optional['ExecutionContext'],
    ) -> None:
        """
        P0: Process SkillOutputContract after node execution.
        1. Adapt raw output to SkillOutputContract via OutputContractAdapter
        2. Reject BINARY+INLINE, record invalid_transport event
        3. Register PRODUCED+ARTIFACT outputs in ArtifactRegistry
        4. Store contract in node.metadata["output_contract"]
        """
        session_id = None
        if context:
            session_id = (
                (context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None)
                or getattr(getattr(context, "identity", None), "session_id", None)
                or (context.variables.get("session_id") if hasattr(context, "variables") else None)
            )

        try:
            contract = self._output_contract_adapter.adapt(
                raw_output=outputs,
                mode=self.output_compat_mode,
                trace_store=self.trace_store,
                session_id=session_id,
            )
        except InvalidTransportError as e:
            # BINARY+INLINE: record event and skip
            logger.warning(f"[GraphExecutor] Node {node.id}: {e}")
            if self.trace_store and session_id:
                try:
                    self.trace_store.record_event(
                        session_id=session_id,
                        event_type="invalid_transport",
                        payload={
                            "node_id": node.id,
                            "reason": str(e),
                            "output_keys": list(outputs.keys()),
                        },
                    )
                except Exception:
                    pass
            return
        except Exception as e:
            logger.warning(f"[GraphExecutor] Node {node.id} output contract adapt failed: {e}")
            return

        if node.metadata is None:
            node.metadata = {}
        node.metadata["output_contract"] = contract

        # Register artifact if role=PRODUCED and transport=ARTIFACT
        if (
            contract.artifact_role == ArtifactRole.PRODUCED
            and contract.transport_mode == TransportMode.ARTIFACT
            and self.artifact_registry
        ):
            await self._register_artifact(node, outputs, contract, session_id)

    async def _register_artifact(
        self,
        node: 'StepNode',
        outputs: Dict[str, Any],
        contract: Any,
        session_id: Optional[str],
    ) -> None:
        """Register a PRODUCED+ARTIFACT output in ArtifactRegistry."""
        try:
            from app.avatar.runtime.artifact.registry import ArtifactType

            # Determine file path from outputs
            path = (
                outputs.get("file_path")
                or outputs.get("output_path")
                or outputs.get("path")
            )
            if not path:
                logger.debug(f"[GraphExecutor] Node {node.id}: no path found for artifact registration")
                return

            # Map ValueKind to ArtifactType
            vk_to_type = {
                ValueKind.BINARY: ArtifactType.BINARY,
                ValueKind.JSON: ArtifactType.JSON_BLOB,
                ValueKind.TABLE: ArtifactType.TABLE,
                ValueKind.TEXT: ArtifactType.FILE,
                ValueKind.PATH: ArtifactType.FILE,
            }
            artifact_type = vk_to_type.get(contract.value_kind, ArtifactType.FILE)
            if contract.mime_type and contract.mime_type.startswith("image/"):
                artifact_type = ArtifactType.IMAGE

            artifact = self.artifact_registry.register(
                path=str(path),
                producer_step=node.id,
                artifact_type=artifact_type,
                semantic_label=contract.semantic_label,
            )
            # Store artifact_id back into contract and node metadata
            contract.artifact_id = artifact.id
            if node.metadata is None:
                node.metadata = {}
            node.metadata["artifact_id"] = artifact.id
            logger.debug(f"[GraphExecutor] Node {node.id}: registered artifact {artifact.id}")
        except Exception as e:
            logger.warning(f"[GraphExecutor] Node {node.id}: artifact registration failed: {e}")

    def _resolve_parameters(
        self,
        graph: 'ExecutionGraph',
        node: 'StepNode',
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        incoming = graph.get_incoming_edges(node.id)
        if not incoming:
            return resolved

        edges_by_param: Dict[str, List['DataEdge']] = {}
        for edge in incoming:
            edges_by_param.setdefault(edge.target_param, []).append(edge)

        for target_param, edges in edges_by_param.items():
            try:
                if len(edges) == 1:
                    resolved[target_param] = self._resolve_single_edge(graph, edges[0], context)
                else:
                    resolved[target_param] = self._merge_multiple_edges(graph, edges, context)
            except Exception as e:
                raise ParameterResolutionError(
                    f"Failed to resolve '{target_param}' for node {node.id}: {e}"
                )

        return resolved

    def _resolve_single_edge(
        self,
        graph: 'ExecutionGraph',
        edge: 'DataEdge',
        context: Optional['ExecutionContext'] = None,
    ) -> Any:
        source_node = graph.nodes.get(edge.source_node)
        if source_node is None:
            raise ParameterResolutionError(f"Source node '{edge.source_node}' not found")

        if source_node.status.value != "success":
            raise ParameterResolutionError(
                f"Source node '{edge.source_node}' not completed (status: {source_node.status.value})"
            )

        if context:
            node_outputs = context.get_node_output(edge.source_node)
            if node_outputs and edge.source_field in node_outputs:
                value = node_outputs[edge.source_field]
            elif edge.source_field in source_node.outputs:
                value = source_node.outputs[edge.source_field]
            else:
                raise ParameterResolutionError(
                    f"Field '{edge.source_field}' not found in '{edge.source_node}' outputs. "
                    f"Available: {list(source_node.outputs.keys())}"
                )
        else:
            if edge.source_field not in source_node.outputs:
                raise ParameterResolutionError(
                    f"Field '{edge.source_field}' not found in '{edge.source_node}' outputs"
                )
            value = source_node.outputs[edge.source_field]

        if edge.transformer_name:
            value = self._apply_transformer(edge.transformer_name, value, edge)

        return value

    def _apply_transformer(self, transformer_name: str, value: Any, edge: 'DataEdge') -> Any:
        if transformer_name not in self.transformer_registry:
            raise TransformerError(f"Unknown transformer '{transformer_name}'")
        try:
            return self.transformer_registry[transformer_name](value)
        except Exception as e:
            raise TransformerError(f"Transformer '{transformer_name}' failed: {e}")

    def _merge_multiple_edges(
        self,
        graph: 'ExecutionGraph',
        edges: List['DataEdge'],
        context: Optional['ExecutionContext'] = None,
    ) -> Any:
        values = [self._resolve_single_edge(graph, e, context) for e in edges]
        first = values[0]

        if isinstance(first, list):
            result = []
            for v in values:
                result.extend(v) if isinstance(v, list) else result.append(v)
            return result
        elif isinstance(first, dict):
            result = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            return result
        else:
            return values[-1]

    async def _execute_skill(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        """
        Execute a skill directly via skill_registry.
        Supports both direct skill names (e.g. 'fs.read') and
        legacy capability names that map to a single skill.

        For python.run: automatically prepends all completed node outputs as
        variables so Planner can reference them by name ({node_id}_output).
        """
        from app.avatar.skills.registry import skill_registry
        from app.avatar.runtime.executor.factory import ExecutorFactory
        from app.avatar.skills.context import SkillContext

        skill_cls = skill_registry.get(skill_name)

        if skill_cls is None:
            raise ExecutionError(
                f"Skill '{skill_name}' not found in registry. "
                f"Available: {list(skill_registry._skills.keys())}"
            )

        # base_path 始终用 user workspace，保证 fs.read/write 等 skill 路径正确。
        # session_workspace 优先从 ExecutionContext 取（按 session_id 动态创建），
        # 其次 fallback 到 self.workspace（向后兼容）。
        base_path = self._get_base_path()

        # python.run: inject upstream node outputs as variables
        if skill_name == "python.run" and context is not None:
            params = self._inject_node_outputs_into_code(params, context)
            # Sanitize host paths in LLM-generated code: replace D:\Temp\IA\... with /workspace/...
            # This prevents SyntaxError from unescaped backslashes in Windows paths
            params = self._sanitize_code_host_paths(params)

        # 构建 extra：workspace 优先从 context 取，保证 session 隔离
        extra: Dict[str, Any] = {}
        _ctx_workspace = getattr(context, "workspace", None) if context is not None else None
        _effective_workspace = _ctx_workspace or self.workspace

        # browser.run artifact 落到 session_workspace/output/，让 ArtifactCollector 能扫到
        if _effective_workspace is not None and hasattr(skill_cls, "spec"):
            from app.avatar.skills.base import SideEffect as _SE
            _side_effects = getattr(skill_cls.spec, "side_effects", set())
            if _SE.BROWSER in _side_effects:
                base_path = _effective_workspace.output_dir
            # net.download 落到 session_workspace root，保证容器内可达
            elif _SE.NETWORK in _side_effects and _SE.FS in _side_effects:
                base_path = Path(_effective_workspace.root)
        if _effective_workspace is not None:
            extra["workspace"] = _effective_workspace
        # 注入 exec_session_id，子进程查 Grant 时用于 scope_id 精确匹配
        if context is not None and getattr(context, "env", None):
            _exec_sid = context.env.get("exec_session_id") if isinstance(context.env, dict) else None
            if _exec_sid:
                extra["exec_session_id"] = _exec_sid
                logger.debug(f"[GraphExecutor] Injected exec_session_id={_exec_sid!r} into SkillContext.extra")
            else:
                logger.warning(f"[GraphExecutor] exec_session_id not found in context.env for skill={skill_name}")
        try:
            from app.avatar.runtime.storage.file_registry import FileRegistry
            if not hasattr(self, "_file_registry") or self._file_registry is None:
                self._file_registry = FileRegistry()
            extra["file_registry"] = self._file_registry
        except Exception as e:
            logger.warning(f"[GraphExecutor] FileRegistry init failed: {e}")

        ctx = SkillContext(
            base_path=base_path,
            workspace_root=base_path,
            dry_run=False,
            memory_manager=self.memory_manager,
            learning_manager=self.learning_manager,
            extra=extra,
        )

        try:
            input_obj = skill_cls.spec.input_model(**params)
        except Exception as e:
            raise ExecutionError(f"Invalid parameters for skill '{skill_name}': {e}")

        executor = ExecutorFactory.get_executor(skill_cls)
        skill_instance = skill_cls()
        result = await executor.execute(skill_instance, input_obj, ctx)

        if hasattr(result, "model_dump"):
            result_dict = result.model_dump()
        elif isinstance(result, dict):
            result_dict = result
        else:
            result_dict = {"output": str(result), "success": True}

        # 主进程注册文件产物到 FileRegistry（skill 在子进程里无法访问 registry）
        registry = extra.get("file_registry")
        if registry is not None and result_dict.get("success") and result_dict.get("file_path"):
            try:
                from pathlib import Path as _Path
                registry.register(
                    file_path=_Path(result_dict["file_path"]),
                    sha256=result_dict.get("sha256", ""),
                    size=result_dict.get("size", 0),
                    mime_type=result_dict.get("mime_type", ""),
                    source_url=result_dict.get("url", ""),
                    skill_name=skill_name,
                )
            except Exception as e:
                logger.warning(f"[GraphExecutor] FileRegistry registration failed: {e}")

        # 收集 skill 内部 LLM 调用的 usage，累加到 execution session
        _skill_llm_usage = result_dict.get("llm_usage")
        _skill_llm_model = result_dict.get("llm_model")
        if _skill_llm_usage and context is not None:
            _exec_sid = context.env.get("exec_session_id") if isinstance(getattr(context, "env", None), dict) else None
            if _exec_sid:
                try:
                    from app.avatar.runtime.graph.planner.graph_planner import _estimate_cost
                    from app.services.session_store import ExecutionSessionStore
                    from sqlmodel import Session, text as _text
                    from app.db.database import engine as _engine
                    _tokens = _skill_llm_usage.get("total_tokens", 0)
                    _cost = _estimate_cost(model=_skill_llm_model or "", usage=_skill_llm_usage)
                    with Session(_engine) as _db:
                        _db.exec(
                            _text(
                                "UPDATE execution_sessions SET "
                                "planner_tokens = planner_tokens + :tokens, "
                                "planner_cost_usd = planner_cost_usd + :cost "
                                "WHERE id = :sid"
                            ).bindparams(tokens=_tokens, cost=_cost, sid=_exec_sid)
                        )
                        _db.commit()
                    logger.debug(
                        f"[GraphExecutor] skill={skill_name} llm_usage accumulated: "
                        f"tokens={_tokens}, cost={_cost:.8f}, session={_exec_sid}"
                    )
                except Exception as _e:
                    logger.warning(f"[GraphExecutor] skill llm_usage accumulation failed: {_e}")

        return result_dict

    # Keep _execute_sequential for backward compat with existing tests
    async def _execute_sequential(self, capability_or_skill, params: Dict[str, Any], context: Optional['ExecutionContext'] = None) -> Dict[str, Any]:
        """
        Backward-compatible sequential execution.
        Accepts either a Capability object (legacy) or a skill name string.
        """
        # If it's a legacy Capability object with composed_skills
        if hasattr(capability_or_skill, "composed_skills"):
            from app.avatar.skills.registry import skill_registry
            from app.avatar.runtime.executor.factory import ExecutorFactory
            from app.avatar.skills.context import SkillContext
            from pathlib import Path

            aggregated: Dict[str, Any] = {}
            current_params = dict(params)

            for skill_name in capability_or_skill.composed_skills:
                skill_cls = skill_registry.get(skill_name)
                if skill_cls is None:
                    raise ExecutionError(
                        f"Skill '{skill_name}' not found (required by '{capability_or_skill.name}')"
                    )

                base_path = self._get_base_path()
                extra: Dict[str, Any] = {}
                _ctx_workspace = getattr(context, "workspace", None) if context is not None else None
                _eff_ws = _ctx_workspace or self.workspace
                if _eff_ws is not None:
                    extra["workspace"] = _eff_ws
                if hasattr(self, "_file_registry") and self._file_registry is not None:
                    extra["file_registry"] = self._file_registry
                ctx = SkillContext(
                    base_path=base_path,
                    workspace_root=base_path,
                    dry_run=False,
                    memory_manager=self.memory_manager,
                    learning_manager=self.learning_manager,
                    extra=extra,
                )

                try:
                    input_obj = skill_cls.spec.input_model(**current_params)
                except Exception as e:
                    raise ExecutionError(f"Invalid parameters for skill '{skill_name}': {e}")

                executor = ExecutorFactory.get_executor(skill_cls)
                result = await executor.execute(skill_cls(), input_obj, ctx)

                result_dict = result.model_dump() if hasattr(result, "model_dump") else (result if isinstance(result, dict) else {"output": str(result), "success": True})
                aggregated.update(result_dict)

                if "output" in result_dict:
                    current_params["input"] = result_dict["output"]

            return aggregated

        # Otherwise treat as skill name string
        return await self._execute_skill(str(capability_or_skill), params)

    def _sanitize_code_host_paths(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace host machine absolute paths in python.run code with container paths.
        Prevents SyntaxError from unescaped backslashes in Windows paths like D:\\Temp\\IA\\file.svg.
        """
        code = params.get("code", "")
        if not code:
            return params

        base_path = self._get_base_path()
        if not base_path:
            return params

        from app.avatar.runtime.workspace.session_workspace import CONTAINER_WORKSPACE_PATH
        workspace_root = str(Path(base_path).resolve())

        # Build both forward-slash and backslash variants
        root_fwd = workspace_root.replace("\\", "/").rstrip("/")
        root_back = workspace_root.replace("/", "\\").rstrip("\\")

        import re as _re

        def _replace(m: _re.Match) -> str:
            full = m.group(0)
            normalized = full.replace("\\", "/")
            if normalized.startswith(root_fwd):
                rel = normalized[len(root_fwd):].lstrip("/")
                return f"{CONTAINER_WORKSPACE_PATH}/{rel}" if rel else CONTAINER_WORKSPACE_PATH
            return full

        escaped_fwd = _re.escape(root_fwd)
        escaped_back = _re.escape(root_back)
        pattern = f"({escaped_fwd}|{escaped_back})[^\\s\"'\\)\\]]*"
        new_code = _re.sub(pattern, _replace, code)

        if new_code != code:
            logger.debug("[GraphExecutor] Sanitized host paths in python.run code")
            return {**params, "code": new_code}
        return params

    def _inject_node_outputs_into_code(
        self,
        params: Dict[str, Any],
        context: 'ExecutionContext',
    ) -> Dict[str, Any]:
        """
        把上游节点输出写成 typed input artifacts，通过文件传入容器。

        每个上游输出写成一个 JSON 文件（对于 JSON 可序列化的值），
        或直接引用文件路径（对于文件产物）。
        同时写一个 manifest.json 列出所有输入。

        容器内固定读取方式：
            import json
            with open('/workspace/input/{node_id}_output.json') as f:
                {node_id}_output = json.load(f)

        结构化输出协议：
            调用 _output(value) 把结构化数据传给下游节点。
            框架从 stdout 中识别 __OUTPUT__:<json> 标记行提取数据。

        文件路径产物（file_path 字段）直接映射为容器内路径，不再 JSON 化内容。
        """
        from app.avatar.runtime.workspace.session_workspace import CONTAINER_WORKSPACE_PATH

        all_outputs = context.get_all_node_outputs()
        if not all_outputs:
            return self._inject_output_helper(params)

        # 优先从 context 取 workspace（session 隔离），fallback 到 self.workspace
        _effective_ws = getattr(context, "workspace", None) or self.workspace
        if _effective_ws is None:
            return self._inject_node_outputs_repr_fallback(params, context)

        workspace_root = str(Path(_effective_ws.root).resolve())
        inputs_dir = Path(_effective_ws.root) / "input"  # 使用标准 input/ 目录
        inputs_dir.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, Any] = {}
        load_lines: List[str] = []

        for node_id, outputs in all_outputs.items():
            if not outputs:
                continue
            if isinstance(outputs, dict) and set(outputs.keys()) == {"__artifacts__"}:
                continue

            var_name = f"{node_id}_output"

            # 提取最有意义的值：结构化输出优先于原始打印
            value = (
                outputs.get("output")
                or outputs.get("result")
                or outputs.get("content")
                or outputs.get("stdout")
                or outputs
            )

            # 文件路径产物：直接映射容器内路径，不 JSON 化内容
            # 优先识别 _save_binary 输出的结构化对象 {"__file__": path}
            file_path_str = None
            if isinstance(outputs, dict):
                _out = outputs.get("output")
                if isinstance(_out, dict) and "__file__" in _out:
                    file_path_str = _out["__file__"]
                else:
                    file_path_str = outputs.get("file_path")
            if file_path_str:
                _fp = str(file_path_str)
                # 容器内路径（/workspace/...）：直接用，不走宿主机 Path.resolve()
                if _fp.startswith("/workspace/") or _fp.startswith("/workspace\\"):
                    container_path = _fp.replace("\\", "/")
                else:
                    # 宿主机绝对路径：映射到容器内路径
                    host_path = str(Path(_fp).resolve())
                    if host_path.startswith(workspace_root):
                        rel = host_path[len(workspace_root):].lstrip("/\\").replace("\\", "/")
                        container_path = f"{CONTAINER_WORKSPACE_PATH}/{rel}"
                    else:
                        container_path = _fp.replace("\\", "/")
                manifest[var_name] = {
                    "format": "file_ref",
                    "container_path": container_path,
                    "type": type(value).__name__,
                }
                load_lines.append(f'{var_name} = "{container_path}"')
                continue

            # 结构化数据：序列化为 JSON 文件
            json_filename = f"{var_name}.json"
            json_path = inputs_dir / json_filename
            container_json_path = f"{CONTAINER_WORKSPACE_PATH}/input/{json_filename}"

            try:
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(value, f, ensure_ascii=False, default=str)
                manifest[var_name] = {
                    "format": "json",
                    "container_path": container_json_path,
                    "type": type(value).__name__,
                }
                load_lines.append(
                    f'with open("{container_json_path}", encoding="utf-8") as _f:\n'
                    f'    {var_name} = json.load(_f)'
                )
            except Exception as e:
                logger.warning(f"[GraphExecutor] Failed to serialize {var_name} to JSON: {e}, falling back to repr")
                repr_val = repr(value)
                load_lines.append(f"{var_name} = {repr_val}")
                manifest[var_name] = {"format": "repr_fallback", "type": type(value).__name__}

        # 写 manifest.json
        manifest_path = inputs_dir / "manifest.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[GraphExecutor] Failed to write manifest: {e}")

        if not load_lines:
            return self._inject_output_helper(params)

        injected_prefix = "import json\n" + "\n".join(load_lines) + "\n\n"
        original_code = params.get("code", "")
        return {**params, "code": injected_prefix + self._output_helper_code() + original_code}

    # ------------------------------------------------------------------
    # _output() 显式结构化输出通道
    # ------------------------------------------------------------------

    _OUTPUT_MARKER = "__OUTPUT__:"

    def _output_helper_code(self) -> str:
        """注入到每个 python.run 代码头部的辅助函数定义"""
        marker = self._OUTPUT_MARKER
        return (
            "import json as _json\n"
            "import os as _os\n"
            f"def _output(value):\n"
            f"    print('{marker}' + _json.dumps(value, ensure_ascii=False, default=str))\n"
            "\n"
            "def _save_binary(path, hex_str):\n"
            "    \"\"\"\n"
            "    把 hex 字符串写成二进制文件。\n"
            "    始终写到 /workspace（Docker 沙箱挂载点）或 cwd（本地执行）下。\n"
            "    写完后通过 _output() 输出结构化对象 {\"__file__\": path}，供框架识别为文件产物。\n"
            "    \"\"\"\n"
            "    _clean = ''.join(hex_str.split())\n"
            "    _data = bytes.fromhex(_clean)\n"
            "    _ws = '/workspace' if _os.path.isdir('/workspace') else _os.getcwd()\n"
            "    # 无论传入绝对路径还是相对路径，都确保落在 workspace 下\n"
            "    if _os.path.isabs(path):\n"
            "        # 绝对路径：只取文件名部分，放到 workspace 根目录\n"
            "        _abs = _os.path.join(_ws, _os.path.basename(path))\n"
            "    else:\n"
            "        _abs = _os.path.join(_ws, path)\n"
            "    _dir = _os.path.dirname(_abs)\n"
            "    if _dir:\n"
            "        _os.makedirs(_dir, exist_ok=True)\n"
            "    with open(_abs, 'wb') as _f:\n"
            "        _f.write(_data)\n"
            "    _output({'__file__': _abs, 'path': _abs})\n"
            "\n"
        )

    def _inject_output_helper(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """无上游输出时，仅注入 _output() helper"""
        original_code = params.get("code", "")
        return {**params, "code": self._output_helper_code() + original_code}

    def _inject_node_outputs_repr_fallback(
        self,
        params: Dict[str, Any],
        context: 'ExecutionContext',
    ) -> Dict[str, Any]:
        """无 session workspace 时的兜底：repr 注入（旧行为）+ _output() helper"""
        all_outputs = context.get_all_node_outputs()

        lines: List[str] = []
        for node_id, outputs in all_outputs.items():
            if not outputs:
                continue
            value = (
                outputs.get("output")
                or outputs.get("content")
                or outputs.get("stdout")
                or outputs
            )
            if isinstance(value, dict) and set(value.keys()) == {"__artifacts__"}:
                continue
            lines.append(f"{node_id}_output = {repr(value)}")

        injected_prefix = "\n".join(lines) + "\n\n" if lines else ""
        original_code = params.get("code", "")
        return {**params, "code": injected_prefix + self._output_helper_code() + original_code}

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
