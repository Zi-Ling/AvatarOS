"""
触发器管理器：触发器 CRUD + Schedule 集成 + 幂等保护。

职责：
- create_trigger: 创建触发器（cron 类型集成 SchedulerService）
- fire_trigger: 触发工作流执行（version_mode 解析 + 参数合并）
- on_workflow_completed: 链式触发（幂等保护）
- delete_trigger / update_trigger: 管理操作
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.db.database import engine
from app.services.workflow.models import (
    TriggerType,
    VersionMode,
    WorkflowInstance,
    WorkflowTemplate,
    WorkflowTrigger,
    WorkflowTriggerLog,
    _now,
    _uuid,
)

logger = logging.getLogger(__name__)


class TriggerManager:
    """触发器管理 + Schedule 集成 + 幂等保护。"""

    def __init__(self, instance_manager, scheduler_service=None, event_bus=None):
        self._instance_manager = instance_manager
        self._scheduler_service = scheduler_service
        # 订阅 EventBus 的工作流完成事件（解耦 InstanceManager）
        if event_bus is not None:
            self._subscribe_to_event_bus(event_bus)

    def _subscribe_to_event_bus(self, event_bus) -> None:
        """订阅 WORKFLOW_INSTANCE_COMPLETED 事件。"""
        try:
            from app.avatar.runtime.events.types import EventType
            def _on_workflow_completed_event(event):
                payload = event.payload
                instance_id = payload.get("instance_id")
                if not instance_id:
                    return
                # 从 DB 加载完整 instance 对象
                from sqlmodel import Session
                from app.db.database import engine
                with Session(engine) as db:
                    inst = db.get(WorkflowInstance, instance_id)
                if inst:
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self.on_workflow_completed(inst))
                    except RuntimeError:
                        # 没有 running loop，跳过
                        logger.warning("[TriggerManager] No running event loop for chain trigger")
            event_bus.subscribe(EventType.WORKFLOW_INSTANCE_COMPLETED, _on_workflow_completed_event)
            logger.info("[TriggerManager] Subscribed to WORKFLOW_INSTANCE_COMPLETED via EventBus")
        except Exception as exc:
            logger.warning(f"[TriggerManager] Failed to subscribe to EventBus: {exc}")

    # ------------------------------------------------------------------
    # create_trigger
    # ------------------------------------------------------------------

    def create_trigger(
        self,
        template_id: str,
        trigger_type: str,
        template_version_id: Optional[str] = None,
        version_mode: str = VersionMode.FIXED.value,
        cron_expression: Optional[str] = None,
        source_workflow_template_id: Optional[str] = None,
        default_params: Optional[dict[str, Any]] = None,
    ) -> WorkflowTrigger:
        """
        创建触发器。

        - cron: 创建 Schedule + APScheduler job
        - workflow_completed: 注册事件监听
        - manual/api: 只创建记录
        """
        # fixed 模式必须指定 version_id
        if version_mode == VersionMode.FIXED.value and not template_version_id:
            # 自动使用 latest_version_id
            with Session(engine) as db:
                tpl = db.get(WorkflowTemplate, template_id)
                if tpl and tpl.latest_version_id:
                    template_version_id = tpl.latest_version_id
                else:
                    raise ValueError("Fixed mode requires template_version_id or template must have a version")

        now = _now()
        trigger = WorkflowTrigger(
            id=_uuid(),
            template_id=template_id,
            template_version_id=template_version_id,
            version_mode=version_mode,
            trigger_type=trigger_type,
            cron_expression=cron_expression,
            source_workflow_template_id=source_workflow_template_id,
            default_params=default_params or {},
            created_at=now,
            updated_at=now,
        )

        with Session(engine) as db:
            db.add(trigger)
            db.commit()
            db.refresh(trigger)

        # cron 类型：注册 Schedule job
        if trigger_type == TriggerType.CRON.value and cron_expression and self._scheduler_service:
            self._register_cron_job(trigger)

        logger.info(f"[TriggerManager] Created trigger {trigger.id} type={trigger_type}")
        return trigger

    # ------------------------------------------------------------------
    # fire_trigger
    # ------------------------------------------------------------------

    async def fire_trigger(
        self,
        trigger_id: str,
        extra_params: Optional[dict[str, Any]] = None,
    ) -> WorkflowInstance:
        """
        触发工作流执行。

        1. 确定 version_id（fixed / latest）
        2. 合并参数
        3. 调用 instance_manager.create_and_run
        """
        with Session(engine) as db:
            trigger = db.get(WorkflowTrigger, trigger_id)
            if not trigger:
                raise ValueError(f"Trigger not found: {trigger_id}")
            if not trigger.is_active:
                raise ValueError(f"Trigger is inactive: {trigger_id}")

            # 确定 version_id
            if trigger.version_mode == VersionMode.LATEST.value:
                tpl = db.get(WorkflowTemplate, trigger.template_id)
                if not tpl or not tpl.latest_version_id:
                    raise ValueError(f"Template has no version: {trigger.template_id}")
                version_id = tpl.latest_version_id
            else:
                version_id = trigger.template_version_id
                if not version_id:
                    raise ValueError(f"Fixed trigger has no version_id: {trigger_id}")

            # 合并参数
            params = dict(trigger.default_params or {})
            if extra_params:
                params.update(extra_params)

        return await self._instance_manager.create_and_run(
            template_version_id=version_id,
            params=params,
            trigger_id=trigger_id,
        )

    # ------------------------------------------------------------------
    # on_workflow_completed（幂等保护）
    # ------------------------------------------------------------------

    async def on_workflow_completed(self, completed_instance: WorkflowInstance) -> None:
        """
        工作流完成事件处理。

        1. 查找 workflow_completed 类型触发器
        2. 幂等检查（TriggerLog 去重）
        3. 上游 outputs 传递为下游参数
        4. 触发下游
        """
        with Session(engine) as db:
            triggers = db.exec(
                select(WorkflowTrigger).where(
                    WorkflowTrigger.trigger_type == TriggerType.WORKFLOW_COMPLETED.value,
                    WorkflowTrigger.source_workflow_template_id == completed_instance.template_id,
                    WorkflowTrigger.is_active == True,
                )
            ).all()

        for trigger in triggers:
            # 幂等检查
            if self._is_already_triggered(trigger.id, completed_instance.id):
                logger.info(
                    f"[TriggerManager] Skipping duplicate trigger "
                    f"{trigger.id} for instance {completed_instance.id}"
                )
                continue

            try:
                # 上游 outputs 作为下游参数
                upstream_outputs = completed_instance.outputs or {}
                # 扁平化：如果 outputs 是 {step_id: {k:v}} 格式，合并为单层
                flat_params = {}
                for step_outputs in upstream_outputs.values():
                    if isinstance(step_outputs, dict):
                        flat_params.update(step_outputs)

                instance = await self.fire_trigger(
                    trigger.id, extra_params=flat_params
                )

                # 记录触发日志
                self._log_trigger(trigger.id, completed_instance.id, instance.id)

            except Exception as exc:
                logger.error(
                    f"[TriggerManager] Failed to fire trigger {trigger.id}: {exc}"
                )

    # ------------------------------------------------------------------
    # delete_trigger / update_trigger
    # ------------------------------------------------------------------

    def delete_trigger(self, trigger_id: str) -> None:
        """删除触发器，同时清理 Schedule job。"""
        with Session(engine) as db:
            trigger = db.get(WorkflowTrigger, trigger_id)
            if not trigger:
                raise ValueError(f"Trigger not found: {trigger_id}")

            # 清理 cron job
            if trigger.schedule_id and self._scheduler_service:
                try:
                    self._scheduler_service.scheduler.remove_job(trigger.schedule_id)
                except Exception:
                    pass

            db.delete(trigger)
            db.commit()

        logger.info(f"[TriggerManager] Deleted trigger {trigger_id}")

    def update_trigger(
        self,
        trigger_id: str,
        version_mode: Optional[str] = None,
        template_version_id: Optional[str] = None,
        cron_expression: Optional[str] = None,
        default_params: Optional[dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> WorkflowTrigger:
        """更新触发器配置。"""
        with Session(engine) as db:
            trigger = db.get(WorkflowTrigger, trigger_id)
            if not trigger:
                raise ValueError(f"Trigger not found: {trigger_id}")

            if version_mode is not None:
                trigger.version_mode = version_mode
            if template_version_id is not None:
                trigger.template_version_id = template_version_id
            if cron_expression is not None:
                trigger.cron_expression = cron_expression
            if default_params is not None:
                trigger.default_params = default_params
            if is_active is not None:
                trigger.is_active = is_active
            trigger.updated_at = _now()

            db.add(trigger)
            db.commit()
            db.refresh(trigger)

        # 更新 cron job
        if cron_expression and trigger.trigger_type == TriggerType.CRON.value:
            self._update_cron_job(trigger)

        return trigger

    def get_trigger(self, trigger_id: str) -> Optional[WorkflowTrigger]:
        with Session(engine) as db:
            return db.get(WorkflowTrigger, trigger_id)

    def list_triggers(
        self, template_id: Optional[str] = None
    ) -> list[WorkflowTrigger]:
        with Session(engine) as db:
            stmt = select(WorkflowTrigger)
            if template_id:
                stmt = stmt.where(WorkflowTrigger.template_id == template_id)
            return list(db.exec(stmt).all())

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _register_cron_job(self, trigger: WorkflowTrigger) -> None:
        """为 cron 触发器注册 Schedule job。"""
        if not self._scheduler_service:
            return
        try:
            schedule = self._scheduler_service.create_schedule(
                name=f"workflow_trigger_{trigger.id}",
                cron=trigger.cron_expression,
                intent={"workflow_trigger_id": trigger.id},
            )
            # 更新 trigger 的 schedule_id
            with Session(engine) as db:
                t = db.get(WorkflowTrigger, trigger.id)
                if t:
                    t.schedule_id = schedule.id
                    db.add(t)
                    db.commit()
        except Exception as exc:
            logger.error(f"[TriggerManager] Failed to register cron job: {exc}")

    def _update_cron_job(self, trigger: WorkflowTrigger) -> None:
        """更新 cron job 的表达式。"""
        if not self._scheduler_service or not trigger.schedule_id:
            return
        try:
            # 移除旧 job，重新创建
            self._scheduler_service.scheduler.remove_job(trigger.schedule_id)
            self._register_cron_job(trigger)
        except Exception as exc:
            logger.error(f"[TriggerManager] Failed to update cron job: {exc}")

    @staticmethod
    def _is_already_triggered(trigger_id: str, source_instance_id: str) -> bool:
        """幂等检查：(trigger_id, source_instance_id) 是否已有记录。"""
        with Session(engine) as db:
            existing = db.exec(
                select(WorkflowTriggerLog).where(
                    WorkflowTriggerLog.trigger_id == trigger_id,
                    WorkflowTriggerLog.source_instance_id == source_instance_id,
                )
            ).first()
            return existing is not None

    @staticmethod
    def _log_trigger(
        trigger_id: str, source_instance_id: str, created_instance_id: str
    ) -> None:
        """记录触发日志（用于幂等去重）。"""
        log = WorkflowTriggerLog(
            id=_uuid(),
            trigger_id=trigger_id,
            source_instance_id=source_instance_id,
            created_instance_id=created_instance_id,
            created_at=_now(),
        )
        with Session(engine) as db:
            db.add(log)
            db.commit()
