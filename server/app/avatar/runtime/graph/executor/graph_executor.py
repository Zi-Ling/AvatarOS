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

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.models.step_node import StepNode
    from app.avatar.runtime.graph.models.data_edge import DataEdge
    from app.avatar.runtime.graph.storage.artifact_store import ArtifactStore
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

ARTIFACT_SIZE_THRESHOLD = 1 * 1024 * 1024

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    pass

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
    ):
        self.transformer_registry = transformer_registry or {}
        self.artifact_store = artifact_store
        self.granted_permissions: List[str] = granted_permissions or []
        self._fallback_base_path = Path(base_path) if base_path else Path(".")
        self.memory_manager = memory_manager
        self.learning_manager = learning_manager
        self.workspace = workspace

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
                raise ExecutionError(
                    outputs.get("message") or outputs.get("error") or "Skill returned success=false"
                )

            if self.artifact_store:
                outputs = await self._offload_large_outputs(outputs, node.id, context)

            if context:
                context.set_node_output(node.id, outputs)
            node.mark_success(outputs)

            logger.info(f"[GraphExecutor] Node {node.id} completed in {latency:.3f}s")

        except Exception as e:
            end_time = datetime.now()
            latency = (end_time - start_time).total_seconds()
            if node.metadata is None:
                node.metadata = {}
            node.metadata["execution_latency"] = latency
            logger.error(f"[GraphExecutor] Node {node.id} failed: {e}", exc_info=True)
            raise  # 让 NodeRunner 的 retry 逻辑接管

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

        # 构建 extra：workspace 优先从 context 取，保证 session 隔离
        extra: Dict[str, Any] = {}
        _ctx_workspace = getattr(context, "workspace", None) if context is not None else None
        _effective_workspace = _ctx_workspace or self.workspace
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
                or outputs.get("content")
                or outputs.get("stdout")
                or outputs
            )

            # 文件路径产物：直接映射容器内路径，不 JSON 化内容
            file_path_str = outputs.get("file_path") if isinstance(outputs, dict) else None
            if file_path_str:
                host_path = str(Path(file_path_str).resolve())
                if host_path.startswith(workspace_root):
                    rel = host_path[len(workspace_root):].lstrip("/\\").replace("\\", "/")
                    container_path = f"{CONTAINER_WORKSPACE_PATH}/{rel}"
                else:
                    container_path = host_path.replace("\\", "/")
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
        """注入到每个 python.run 代码头部的 _output() 函数定义"""
        marker = self._OUTPUT_MARKER
        return (
            "import json as _json\n"
            f"def _output(value):\n"
            f"    print('{marker}' + _json.dumps(value, ensure_ascii=False, default=str))\n"
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
