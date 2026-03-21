"""
Skill execution mixin for GraphExecutor.

Handles executing skills via skill_registry, including code injection,
path sanitization, workspace setup, and LLM usage tracking.

Extracted from graph_executor.py to keep the executor module focused on
core execution logic.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging
from pathlib import Path

if TYPE_CHECKING:
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Skill execution failure. retryable=False means no retry should be attempted."""
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class SkillExecutorMixin:
    """Mixin providing skill execution methods for GraphExecutor."""

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
        base_path = self._get_base_path()

        # python.run: inject upstream node outputs as variables
        _code_params = getattr(skill_cls.spec, "code_params", set()) if hasattr(skill_cls, "spec") else set()
        if _code_params and context is not None:
            # 判断该 skill 是否会在 Docker/Sandbox 中执行，
            # 以决定注入代码中的路径应该用容器路径还是宿主机路径。
            _sandboxed = False
            try:
                from app.avatar.runtime.executor.factory import ExecutorFactory as _EF
                from app.avatar.runtime.executor.sandbox import SandboxExecutor as _SBX
                from app.avatar.runtime.executor.docker import DockerExecutor as _DKR
                _chosen_executor = _EF.get_executor(skill_cls)
                _sandboxed = isinstance(_chosen_executor, (_SBX, _DKR))
            except Exception:
                pass
            params = self._inject_node_outputs_into_code(params, context, sandboxed=_sandboxed)
            params = self._sanitize_code_host_paths(params)

        # 构建 extra：workspace 优先从 context 取，保证 session 隔离
        extra: Dict[str, Any] = {}
        _ctx_workspace = getattr(context, "workspace", None) if context is not None else None
        _effective_workspace = _ctx_workspace or self.workspace

        # browser.run artifact 落到 session_workspace/output/
        if _effective_workspace is not None and hasattr(skill_cls, "spec"):
            from app.avatar.skills.base import SideEffect as _SE
            _side_effects = getattr(skill_cls.spec, "side_effects", set())
            if _SE.BROWSER in _side_effects:
                base_path = _effective_workspace.output_dir
            elif _SE.NETWORK in _side_effects and _SE.FS in _side_effects:
                base_path = Path(_effective_workspace.root)
        if _effective_workspace is not None:
            extra["workspace"] = _effective_workspace
        # 注入 exec_session_id
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

        # 主进程注册文件产物到 FileRegistry
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

        # 收集 skill 内部 LLM 调用的 usage
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
    async def _execute_sequential(
        self,
        capability_or_skill,
        params: Dict[str, Any],
        context: Optional['ExecutionContext'] = None,
    ) -> Dict[str, Any]:
        """
        Backward-compatible sequential execution.
        Accepts either a Capability object (legacy) or a skill name string.
        """
        # If it's a legacy Capability object with composed_skills
        if hasattr(capability_or_skill, "composed_skills"):
            from app.avatar.skills.registry import skill_registry
            from app.avatar.runtime.executor.factory import ExecutorFactory
            from app.avatar.skills.context import SkillContext

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

                result_dict = result.model_dump() if hasattr(result, "model_dump") else (
                    result if isinstance(result, dict) else {"output": str(result), "success": True}
                )
                aggregated.update(result_dict)

                if "output" in result_dict:
                    current_params["input"] = result_dict["output"]

            return aggregated

        # Otherwise treat as skill name string
        return await self._execute_skill(str(capability_or_skill), params)
