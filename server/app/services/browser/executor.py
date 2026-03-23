# server/app/services/browser/executor.py
"""BrowserAutomationStepExecutor — 实现 StepExecutor 接口。"""
from __future__ import annotations

import json
import logging
import time
import traceback
from typing import Any

from app.services.browser.action_dispatcher import ActionDispatcher
from app.services.browser.action_policy import ActionPolicy
from app.services.browser.errors import build_failure_context, normalize_error
from app.services.browser.models import (
    ActionPrimitive,
    ActionPrimitiveType,
    BrowserAutomationConfig,
    BrowserErrorCode,
    ExecutionResult,
    FailurePolicy,
    VerificationSpec,
)
from app.services.browser.session_manager import SessionManager
from app.services.browser.verification_engine import VerificationEngine
from app.services.workflow.models import WorkflowStepDef
from app.services.workflow.step_executor import (
    OutputContractValidator,
    StepExecutor,
    StepRunResult,
)

logger = logging.getLogger(__name__)


# artifact/output 映射规范
_OUTPUT_KEY_MAP: dict[ActionPrimitiveType, str] = {
    ActionPrimitiveType.SCREENSHOT: "screenshot_path",
    ActionPrimitiveType.EXTRACT_TABLE: "table_data",
    ActionPrimitiveType.DOWNLOAD_WAIT: "download_path",
    ActionPrimitiveType.GET_COOKIES: "cookies",
}


class BrowserAutomationStepExecutor(StepExecutor):
    """实现 StepExecutor 接口，集成到 Workflow Orchestration。"""

    def __init__(
        self,
        session_manager: SessionManager,
        dispatcher: ActionDispatcher | None = None,
        verification_engine: VerificationEngine | None = None,
        policy: ActionPolicy | None = None,
        output_validator: OutputContractValidator | None = None,
    ):
        self._session_manager = session_manager
        self._dispatcher = dispatcher or ActionDispatcher()
        self._verification = verification_engine or VerificationEngine()
        self._policy = policy or ActionPolicy()
        self._output_validator = output_validator or OutputContractValidator()

    async def execute(
        self,
        step_def: WorkflowStepDef,
        resolved_inputs: dict[str, Any],
        instance_id: str,
    ) -> StepRunResult:
        start = time.monotonic()
        params = step_def.params
        session_id = params.get("session_id")
        temp_session = False

        try:
            # 1. 解析 actions
            actions_raw = params.get("actions", [])
            actions = [ActionPrimitive(**a) for a in actions_raw]

            # 2. 获取或创建 session/context/page
            if session_id:
                session = await self._session_manager.get_session(session_id)
                if not session:
                    return self._fail_result(
                        "Session not found", BrowserErrorCode.CONTEXT_DESTROYED,
                        start, [], None,
                    )
            else:
                session = await self._session_manager.create_session(
                    workflow_instance_id=instance_id,
                )
                session_id = session.session_id
                temp_session = True

            # 确保有 context 和 page
            contexts = await self._session_manager.list_contexts(session_id)
            if contexts:
                context_id = contexts[0].context_id
            else:
                ctx = await self._session_manager.create_context(session_id)
                context_id = ctx.context_id

            pages = await self._session_manager.list_pages(context_id)
            if pages:
                page_id = pages[0].page_id
            else:
                pg = await self._session_manager.create_page(context_id)
                page_id = pg.page_id

            page = self._get_page_object(page_id)

            # 3. 解析 failure_policy 和 step-level verifications
            failure_policy_str = params.get("failure_policy", "fail_fast")
            try:
                failure_policy = FailurePolicy(failure_policy_str)
            except ValueError:
                failure_policy = FailurePolicy.FAIL_FAST

            step_verifications: list[VerificationSpec] = []
            for v_raw in params.get("verifications", []):
                step_verifications.append(VerificationSpec(**v_raw))

            recording_enabled = params.get("recording_enabled", False)

            # 4. 通过 ActionDispatcher 执行操作序列
            exec_result: ExecutionResult = await self._dispatcher.execute_sequence(
                actions=actions,
                page=page,
                policy=self._policy,
                failure_policy=failure_policy,
                recording_enabled=recording_enabled,
            )

            # 5. step-level 验证
            step_verification_results = []
            if exec_result.success and step_verifications:
                step_verification_results = await self._verification.verify_step(
                    step_verifications, page,
                )
                step_failed = [v for v in step_verification_results if not v.passed]
                if step_failed:
                    exec_result.success = False
                    exec_result.error_message = (
                        f"Step verification failed: {step_failed[0].detail}"
                    )

            # 6. 构建 outputs
            outputs = self._build_outputs(exec_result)

            # 7. 转换为 StepRunResult
            duration = (time.monotonic() - start) * 1000
            if exec_result.success:
                result = StepRunResult(
                    success=True,
                    outputs=outputs,
                    duration_ms=duration,
                )
            else:
                fc = build_failure_context(
                    url=page.url if hasattr(page, "url") else "",
                    title=page.title if hasattr(page, "title") else "",
                    error_code=exec_result.error_code or BrowserErrorCode.UNKNOWN,
                    error_message=exec_result.error_message or "Unknown error",
                    completed_actions=exec_result.action_results,
                    last_page_snapshot=exec_result.final_page_state,
                    error_stack_summary="",
                )
                result = StepRunResult(
                    success=False,
                    outputs=outputs,
                    error=fc.to_json(),
                    duration_ms=duration,
                )

        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            error_code = normalize_error(exc)
            fc = build_failure_context(
                error_code=error_code,
                error_message=str(exc),
                error_stack_summary=traceback.format_exc()[-500:],
            )
            result = StepRunResult(
                success=False,
                outputs={},
                error=fc.to_json(),
                duration_ms=duration,
            )
        finally:
            # 临时会话自动销毁
            if temp_session and session_id:
                try:
                    await self._session_manager.destroy_session(session_id)
                except Exception:
                    logger.warning(f"Failed to destroy temp session {session_id}")

        # OutputContractValidator 校验
        return self._output_validator.validate(step_def, result)

    def _get_page_object(self, page_id: str) -> Any:
        """获取 Playwright page 对象。

        当前实现返回 page_id 作为占位符。
        实际集成 Playwright 时，此处应从 SessionManager 的
        内部 page 注册表中获取真实 page 对象。
        """
        return self._session_manager._pages.get(page_id, page_id)

    @staticmethod
    def _fail_result(
        error_msg: str,
        error_code: BrowserErrorCode,
        start: float,
        completed_actions: list,
        snapshot: Any,
    ) -> StepRunResult:
        """构建失败 StepRunResult。"""
        duration = (time.monotonic() - start) * 1000
        fc = build_failure_context(
            error_code=error_code,
            error_message=error_msg,
            completed_actions=completed_actions,
            last_page_snapshot=snapshot,
        )
        return StepRunResult(
            success=False,
            outputs={},
            error=fc.to_json(),
            duration_ms=duration,
        )

    @staticmethod
    def _build_outputs(exec_result: ExecutionResult) -> dict[str, Any]:
        """从 ExecutionResult 构建 step outputs。

        映射规范：
        - screenshot → outputs["screenshot_path"] (file_path)
        - extract_table → outputs["table_data"] (json)
        - download_wait → outputs["download_path"] (file_path)
        - get_cookies → outputs["cookies"] (json)
        - 其余 → outputs["result"] (json)
        """
        outputs: dict[str, Any] = {}
        for ar in exec_result.action_results:
            if not ar.success or ar.data is None:
                continue
            # 从 ActionResult 推断 action_type（通过 data 结构）
            # 使用 _OUTPUT_KEY_MAP 查找特殊映射
            mapped = False
            for ptype, key in _OUTPUT_KEY_MAP.items():
                if ptype == ActionPrimitiveType.SCREENSHOT and isinstance(ar.data, dict) and "path" in ar.data:
                    outputs[key] = ar.data["path"]
                    mapped = True
                    break
                elif ptype == ActionPrimitiveType.EXTRACT_TABLE and isinstance(ar.data, list):
                    outputs[key] = ar.data
                    mapped = True
                    break
                elif ptype == ActionPrimitiveType.DOWNLOAD_WAIT and isinstance(ar.data, dict) and "download_path" in ar.data:
                    outputs[key] = ar.data["download_path"]
                    mapped = True
                    break
                elif ptype == ActionPrimitiveType.GET_COOKIES and isinstance(ar.data, list) and ar.data and isinstance(ar.data[0], dict):
                    outputs[key] = ar.data
                    mapped = True
                    break
            if not mapped:
                outputs["result"] = ar.data
        return outputs
