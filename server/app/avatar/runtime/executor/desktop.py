# app/avatar/runtime/executor/desktop.py

"""
DesktopExecutor — 专用宿主机 GUI 执行通道

与 LocalExecutor 的区别：
- LocalExecutor: 通用本地执行，无隔离，仅 SAFE 级别
- DesktopExecutor: 受控 GUI 驱动通道，仅允许 computer.* 技能

安全设计：
1. Skill 名称白名单 — 只允许 computer.* 命名空间
2. Action 原语白名单 — 只允许 GUI 原语操作
3. 风险分级 — 危险操作需审批
4. 细粒度审计 — 记录截图、坐标、定位依据、验证结果
5. Break-glass 机制 — 紧急覆盖
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Set, Dict, List

from .base import SkillExecutor, ExecutionStrategy

logger = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────────────────────────

# Skill 名称白名单前缀
ALLOWED_SKILL_PREFIX = "computer."

# Action 原语白名单（允许的 skill 名称后缀）
ALLOWED_ACTION_PRIMITIVES: Set[str] = {
    # 高层自主操控
    "computer.use",
    "computer.read_screen",
    "computer.click_element",
    "computer.type_text",
    "computer.wait_for",
    "computer.fill_form",
    # 鼠标原语
    "computer.mouse.move",
    "computer.mouse.click",
    "computer.mouse.click_at",
    "computer.mouse.drag",
    "computer.mouse.scroll",
    # 键盘原语
    "computer.keyboard.type",
    "computer.keyboard.hotkey",
    "computer.keyboard.press",
    # 屏幕原语
    "computer.screen.capture",
    "computer.screen.info",
    # 应用控制
    "computer.app.launch",
    "computer.window.focus",
}


class RiskTier(str, Enum):
    """GUI 操作风险分级"""
    LOW = "low"          # 截屏、读取、鼠标移动、滚动
    MEDIUM = "medium"    # 普通点击、输入、窗口聚焦
    HIGH = "high"        # 应用启动、组合键、拖拽
    CRITICAL = "critical"  # 保留：未来用于密码输入、支付确认等


# 风险分级映射
RISK_TIER_MAP: Dict[str, RiskTier] = {
    # LOW — 只读 / 无副作用
    "computer.read_screen": RiskTier.LOW,
    "computer.wait_for": RiskTier.LOW,
    "computer.mouse.move": RiskTier.LOW,
    "computer.mouse.scroll": RiskTier.LOW,
    "computer.screen.capture": RiskTier.LOW,
    "computer.screen.info": RiskTier.LOW,
    # MEDIUM — 普通交互
    "computer.mouse.click": RiskTier.MEDIUM,
    "computer.mouse.click_at": RiskTier.MEDIUM,
    "computer.click_element": RiskTier.MEDIUM,
    "computer.type_text": RiskTier.MEDIUM,
    "computer.keyboard.type": RiskTier.MEDIUM,
    "computer.keyboard.press": RiskTier.MEDIUM,
    "computer.fill_form": RiskTier.MEDIUM,
    "computer.window.focus": RiskTier.MEDIUM,
    # HIGH — 潜在危险操作
    "computer.use": RiskTier.HIGH,  # 自主循环，不可预测
    "computer.app.launch": RiskTier.HIGH,  # 启动任意进程
    "computer.keyboard.hotkey": RiskTier.HIGH,  # 组合键可能触发系统操作
    "computer.mouse.drag": RiskTier.HIGH,  # 拖拽可能移动/删除文件
}

# 需要审批的风险等级（HIGH 及以上）
APPROVAL_REQUIRED_TIERS: Set[RiskTier] = {RiskTier.HIGH, RiskTier.CRITICAL}

# Break-glass 环境变量名（紧急覆盖，跳过审批）
BREAK_GLASS_ENV_VAR = "IA_DESKTOP_BREAK_GLASS"


class DesktopExecutor(SkillExecutor):
    """
    专用宿主机 GUI 执行通道

    安全边界：
    - 只允许 computer.* 命名空间的技能
    - 只允许白名单内的 action 原语
    - HIGH/CRITICAL 操作需要 ApprovalService 审批
    - 每次操作记录细粒度审计日志
    """

    def __init__(self, approval_service=None):
        super().__init__()
        self.strategy = ExecutionStrategy.DESKTOP
        self._approval_service = approval_service
        self._audit_log: List[Dict[str, Any]] = []

    def supports(self, skill: Any) -> bool:
        """
        Capability-based 路由：只支持声明了 requires_host_desktop=True 的技能，
        且技能名必须在白名单内。
        """
        try:
            spec = skill.spec
            # 必须声明 requires_host_desktop
            if not getattr(spec, 'requires_host_desktop', False):
                return False
            # 名称必须以 computer. 开头
            if not spec.name.startswith(ALLOWED_SKILL_PREFIX):
                return False
            # 必须在 action 原语白名单内
            if spec.name not in ALLOWED_ACTION_PRIMITIVES:
                logger.warning(
                    f"[DesktopExecutor] Skill {spec.name} has requires_host_desktop=True "
                    f"but is NOT in action primitive whitelist — BLOCKED"
                )
                return False
            return True
        except Exception as e:
            logger.warning(f"[DesktopExecutor] Failed to check support: {e}")
            return False

    async def execute(self, skill: Any, input_data: Any, context: Any) -> Any:
        """
        在宿主机桌面环境执行 GUI 技能

        流程：
        1. 安全检查（白名单 + 原语验证）
        2. 风险评估 + 审批门控
        3. 执行技能
        4. 细粒度审计记录
        """
        spec = skill.spec
        skill_name = spec.name
        start_time = time.time()

        # ── 1. 安全检查 ──
        if not self.supports(skill):
            raise PermissionError(
                f"[DesktopExecutor] Skill '{skill_name}' is not allowed. "
                f"Only whitelisted computer.* primitives can use the desktop execution channel."
            )

        # ── 2. 风险评估 + 审批 ──
        risk_tier = RISK_TIER_MAP.get(skill_name, RiskTier.HIGH)
        approved = await self._check_approval(skill_name, risk_tier, input_data, context)
        if not approved:
            raise PermissionError(
                f"[DesktopExecutor] Skill '{skill_name}' (risk={risk_tier.value}) "
                f"was DENIED by approval gate."
            )

        # ── 3. 执行 ──
        logger.info(f"[DesktopExecutor] Executing {skill_name} (risk={risk_tier.value})")
        try:
            result = skill.run(context, input_data)
            if asyncio.iscoroutine(result):
                result = await result
            execution_time = time.time() - start_time

            # ── 4. 审计 ──
            self._audit_operation(
                skill_name=skill_name,
                risk_tier=risk_tier,
                input_data=input_data,
                result=result,
                execution_time=execution_time,
                success=True,
                context=context,
            )

            logger.info(f"[DesktopExecutor] Success: {skill_name} ({execution_time:.3f}s)")
            return result

        except Exception as e:
            execution_time = time.time() - start_time
            self._audit_operation(
                skill_name=skill_name,
                risk_tier=risk_tier,
                input_data=input_data,
                result=None,
                execution_time=execution_time,
                success=False,
                error=str(e),
                context=context,
            )
            logger.error(f"[DesktopExecutor] Failed: {skill_name}, error: {e}")
            raise

    async def _check_approval(
        self,
        skill_name: str,
        risk_tier: RiskTier,
        input_data: Any,
        context: Any,
    ) -> bool:
        """
        审批门控

        - LOW/MEDIUM: 自动放行
        - HIGH/CRITICAL: 需要 ApprovalService 审批
        - Break-glass: 环境变量覆盖（紧急情况）
        """
        if risk_tier not in APPROVAL_REQUIRED_TIERS:
            return True

        # Break-glass 机制
        import os
        if os.environ.get(BREAK_GLASS_ENV_VAR, "").lower() in ("1", "true", "yes"):
            logger.warning(
                f"[DesktopExecutor] BREAK-GLASS override for {skill_name} "
                f"(risk={risk_tier.value}). This bypasses approval."
            )
            self._audit_operation(
                skill_name=skill_name,
                risk_tier=risk_tier,
                input_data=input_data,
                result=None,
                execution_time=0,
                success=True,
                context=context,
                extra={"break_glass": True},
            )
            return True

        # 无审批服务时，HIGH 自动放行但记录警告，CRITICAL 拒绝
        if self._approval_service is None:
            if risk_tier == RiskTier.CRITICAL:
                logger.error(
                    f"[DesktopExecutor] No ApprovalService available, "
                    f"CRITICAL operation '{skill_name}' DENIED."
                )
                return False
            logger.warning(
                f"[DesktopExecutor] No ApprovalService available, "
                f"auto-approving HIGH operation '{skill_name}'."
            )
            return True

        # 请求审批
        import uuid
        request_id = f"desktop_{skill_name}_{uuid.uuid4().hex[:8]}"
        input_summary = self._summarize_input(input_data)

        self._approval_service.create_request(
            request_id=request_id,
            message=f"GUI 操作审批: {skill_name} (风险等级: {risk_tier.value})",
            operation=f"desktop.{skill_name}",
            details={
                "skill_name": skill_name,
                "risk_tier": risk_tier.value,
                "input_summary": input_summary,
            },
            timeout_seconds=60,
        )

        # Poll for approval decision (ApprovalService is DB-based, no async wait)
        import asyncio as _aio
        timeout_seconds = 60
        poll_interval = 1.0
        elapsed = 0.0
        while elapsed < timeout_seconds:
            req = self._approval_service.get_request(request_id)
            if req and req.get("status") != "pending":
                approved = req.get("status") == "approved"
                logger.info(
                    f"[DesktopExecutor] Approval result for {skill_name}: "
                    f"{req.get('status')} (waited {elapsed:.1f}s)"
                )
                return approved
            await _aio.sleep(poll_interval)
            elapsed += poll_interval

        logger.warning(f"[DesktopExecutor] Approval timeout for {skill_name} after {timeout_seconds}s")
        return False

    def _audit_operation(
        self,
        skill_name: str,
        risk_tier: RiskTier,
        input_data: Any,
        result: Any,
        execution_time: float,
        success: bool,
        context: Any = None,
        error: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        """
        细粒度 GUI 操作审计

        记录：
        - 技能名称 + 风险等级
        - 输入参数（坐标、文本、目标描述）
        - 执行结果（成功/失败、截图引用、定位依据）
        - 耗时
        - 时间戳
        """
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "skill_name": skill_name,
            "risk_tier": risk_tier.value,
            "success": success,
            "execution_time_ms": round(execution_time * 1000, 2),
        }

        # 输入审计
        input_summary = self._summarize_input(input_data)
        audit_entry["input"] = input_summary

        # 输出审计
        if result is not None:
            output_summary = self._summarize_output(result)
            audit_entry["output"] = output_summary

        if error:
            audit_entry["error"] = error

        if extra:
            audit_entry.update(extra)

        # 存储审计记录
        self._audit_log.append(audit_entry)

        # 结构化日志输出
        log_level = logging.INFO if success else logging.ERROR
        logger.log(
            log_level,
            f"[DesktopExecutor] AUDIT: skill={skill_name} "
            f"risk={risk_tier.value} success={success} "
            f"time={execution_time:.3f}s "
            f"input={input_summary}"
            f"{f' error={error}' if error else ''}"
        )

    def _summarize_input(self, input_data: Any) -> Dict[str, Any]:
        """提取 GUI 操作的关键输入参数"""
        summary: Dict[str, Any] = {}
        if input_data is None:
            return summary

        data = input_data
        if hasattr(input_data, 'model_dump'):
            data = input_data.model_dump()

        if isinstance(data, dict):
            # 提取常见 GUI 参数
            for key in ('x', 'y', 'button', 'clicks', 'duration',
                        'text', 'keys', 'goal', 'description',
                        'target_description', 'region', 'name',
                        'title', 'click_type', 'timeout', 'appear',
                        'max_steps', 'interval', 'args'):
                if key in data:
                    val = data[key]
                    # 截断长文本
                    if isinstance(val, str) and len(val) > 100:
                        val = val[:100] + "..."
                    summary[key] = val
        return summary

    def _summarize_output(self, result: Any) -> Dict[str, Any]:
        """提取 GUI 操作的关键输出参数"""
        summary: Dict[str, Any] = {}
        if result is None:
            return summary

        # 提取常见输出字段
        for attr in ('success', 'message', 'clicked_coords', 'target_coords',
                      'confidence', 'locator_source', 'found', 'typed_text',
                      'steps_taken', 'result_summary', 'failure_reason',
                      'filled_fields', 'failed_fields', 'base64_image', 'info'):
            val = getattr(result, attr, None)
            if val is not None:
                # base64 图片只记录长度
                if attr == 'base64_image' and isinstance(val, str):
                    summary[attr] = f"<base64:{len(val)} chars>"
                elif isinstance(val, str) and len(val) > 200:
                    summary[attr] = val[:200] + "..."
                else:
                    summary[attr] = val
        return summary

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """获取审计日志（供外部查询）"""
        return list(self._audit_log)

    def clear_audit_log(self):
        """清空审计日志"""
        self._audit_log.clear()

    def cleanup(self):
        """资源清理"""
        log_count = len(self._audit_log)
        self._audit_log.clear()
        self._approval_service = None
        logger.info(f"[DesktopExecutor] Cleaned up ({log_count} audit entries flushed)")
