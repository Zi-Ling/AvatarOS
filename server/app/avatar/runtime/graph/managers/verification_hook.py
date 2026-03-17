# server/app/avatar/runtime/graph/managers/verification_hook.py
"""
VerificationHook — 阶段级验证钩子

在每个 phase 完成后触发可配置的验证检查：
build / test / lint / assert / user_constraint。
验证失败时阻止进入下一阶段并记录失败原因。
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 默认 phase 验证配置（capability pattern → check types）
_DEFAULT_PHASE_CONFIGS: dict[str, list[str]] = {
    "build.*": ["build", "lint"],
    "test.*": ["test", "assert"],
    "deploy.*": ["build", "test", "lint", "assert"],
    "default": ["build"],
}


class VerificationHook:
    """阶段级验证钩子。"""

    def __init__(self):
        self._phase_configs: dict[str, list[str]] = dict(_DEFAULT_PHASE_CONFIGS)

    async def run_phase_checks(
        self,
        task_session_id: str,
        phase_id: str,
        check_types: list[str],
    ) -> dict:
        """
        执行阶段验证检查。

        Returns:
            {"passed": bool, "failures": list[dict]}
        """
        logger.info(
            f"[VerificationHook] Running phase checks for "
            f"{task_session_id}/{phase_id}: {check_types}"
        )

        failures = []
        for check_type in check_types:
            result = await self._execute_check(task_session_id, phase_id, check_type)
            if not result["passed"]:
                failures.append(result)

        passed = len(failures) == 0

        if not passed:
            logger.warning(
                f"[VerificationHook] Phase {phase_id} failed "
                f"{len(failures)} check(s): "
                f"{[f['check_type'] for f in failures]}"
            )
        else:
            logger.info(
                f"[VerificationHook] Phase {phase_id} passed all checks"
            )

        return {"passed": passed, "failures": failures}

    async def _execute_check(
        self, task_session_id: str, phase_id: str, check_type: str
    ) -> dict:
        """
        执行单个验证检查。

        占位实现：实际集成时会调用 build/test/lint 工具。
        当前默认通过。
        """
        logger.debug(
            f"[VerificationHook] Executing {check_type} check "
            f"for {task_session_id}/{phase_id}"
        )
        # Placeholder: actual checks will be integrated with build/test tools
        return {
            "check_type": check_type,
            "phase_id": phase_id,
            "passed": True,
            "message": f"{check_type} check passed (placeholder)",
        }

    def get_phase_config(self, capability_pattern: str) -> list[str]:
        """获取某类 capability 对应的验证检查配置。"""
        # 精确匹配
        if capability_pattern in self._phase_configs:
            return self._phase_configs[capability_pattern]

        # 前缀匹配
        for pattern, checks in self._phase_configs.items():
            if pattern == "default":
                continue
            prefix = pattern.rstrip(".*")
            if capability_pattern.startswith(prefix):
                return checks

        # 默认
        return self._phase_configs.get("default", ["build"])
