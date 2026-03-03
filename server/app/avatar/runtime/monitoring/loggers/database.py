# app/avatar/runtime/monitoring/loggers/database.py
"""
数据库日志实现
"""
from __future__ import annotations

from typing import Dict, List, Optional, Any

from ..models import StepLogRecord, TaskLog, StepStatus, TaskStatus


class DatabaseStepLogger:
    """
    使用数据库持久化的 StepLogger 实现
    直接使用现有的 Task/Run/Step 表进行记录
    """

    def __init__(self) -> None:
        # 内存索引：task_id -> run_id（用于快速查找）
        self._task_run_map: Dict[str, str] = {}
        # 内存索引：(task_id, step_id) -> db_step_id
        self._step_id_map: Dict[tuple[str, str], str] = {}

    def on_task_start(self, task_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        开始执行一个 task 时被调用
        
        注意：task_id 在这里实际上是 run_id（数据库中的 Run 记录 ID）
        因为 planner.Task 和 db.Run 之间的映射关系已由 AvatarMain 管理
        """
        from app.db import RunStore
        
        # task_id 实际上是 run_id，直接更新状态
        run = RunStore.get(task_id)
        if run:
            # 更新为 running 状态（设置 started_at）
            RunStore.update_status(task_id, "running")
            self._task_run_map[task_id] = task_id

    def on_step_start(self, task_id: str, step: Any) -> None:
        """
        某个 step 即将执行时调用
        
        创建 Step 数据库记录
        """
        from app.db import StepStore
        
        run_id = self._task_run_map.get(task_id, task_id)
        
        # 创建 Step 记录
        step_record = StepStore.create(
            run_id=run_id,
            step_index=getattr(step, "order", 0),
            step_name=getattr(step, "id", ""),
            skill_name=getattr(step, "skill_name", ""),
            input_params=getattr(step, "params", {}) or {},
        )
        
        # 保存映射关系
        step_id = getattr(step, "id", "")
        self._step_id_map[(task_id, step_id)] = step_record.id
        
        # 更新状态为 running
        StepStore.update_status(step_record.id, "running")

    def on_step_end(self, task_id: str, step: Any, result: Any) -> None:
        """
        某个 step 执行结束（不论成功/失败）时调用
        
        更新 Step 记录的结果和状态
        """
        from app.db import StepStore
        
        step_id = getattr(step, "id", "")
        db_step_id = self._step_id_map.get((task_id, step_id))
        
        if not db_step_id:
            # 如果没找到，可能是因为没调用 on_step_start，尝试兜底
            return
        
        # 映射状态
        step_status = getattr(step, "status", StepStatus.SUCCESS)
        if step_status == StepStatus.SUCCESS:
            db_status = "completed"
        elif step_status == StepStatus.FAILED:
            db_status = "failed"
        elif step_status == StepStatus.SKIPPED:
            db_status = "skipped"
        else:
            db_status = "pending"
        
        # 提取结果
        output_result = None
        error_message = None
        
        if result:
            if hasattr(result, "output") and result.output is not None:
                output_result = self._serialize_output(result.output)
            if hasattr(result, "error") and result.error:
                error_message = result.error
        
        # 更新数据库
        StepStore.update_status(
            db_step_id,
            db_status,
            output_result=output_result,
            error_message=error_message,
        )

    def on_task_end(
        self,
        task_id: str,
        status: Any,
        error: Optional[str] = None,
    ) -> None:
        """
        Task 执行完毕时调用
        
        更新 Run 记录的最终状态
        """
        from app.db import RunStore
        
        run_id = self._task_run_map.get(task_id, task_id)
        
        # 映射状态
        if status == TaskStatus.SUCCESS:
            db_status = "completed"
            summary = "✅ 任务成功完成"
        elif status == TaskStatus.FAILED:
            db_status = "failed"
            summary = "❌ 任务执行失败"
        elif status == TaskStatus.PARTIAL_SUCCESS:
            db_status = "completed"
            summary = "⚠️ 任务部分完成"
        else:
            db_status = "running"
            summary = None
        
        RunStore.update_status(
            run_id,
            db_status,
            summary=summary,
            error_message=error,
        )

    def get_task_log(self, task_id: str) -> Optional[TaskLog]:
        """
        获取某个 task 的完整日志
        
        从数据库读取 Run 和 Steps 记录并转换为 TaskLog
        """
        from app.db import RunStore, StepStore
        
        run_id = self._task_run_map.get(task_id, task_id)
        run = RunStore.get(run_id)
        
        if not run:
            return None
        
        # 转换状态
        if run.status == "completed":
            task_status = TaskStatus.SUCCESS
        elif run.status == "failed":
            task_status = TaskStatus.FAILED
        else:
            task_status = TaskStatus.RUNNING
        
        # 构造 TaskLog
        task_log = TaskLog(
            task_id=run_id,
            status=task_status,
            started_at=run.started_at.timestamp() if run.started_at else run.created_at.timestamp(),
            finished_at=run.finished_at.timestamp() if run.finished_at else None,
            error=run.error_message,
        )
        
        # 读取所有步骤
        steps = StepStore.list_by_run(run_id)
        for step in steps:
            # 转换状态
            if step.status == "completed":
                step_status = StepStatus.SUCCESS
            elif step.status == "failed":
                step_status = StepStatus.FAILED
            elif step.status == "skipped":
                step_status = StepStatus.SKIPPED
            else:
                step_status = StepStatus.PENDING
            
            step_log = StepLogRecord(
                id=step.id,
                task_id=run_id,
                step_id=step.step_name,
                order=step.step_index,
                skill_name=step.skill_name,
                status=step_status,
                input_params=step.input_params or {},
                output=step.output_result,
                error=step.error_message,
                retry_count=0,  # 暂时不支持 retry_count（需要扩展表字段）
                started_at=step.started_at.timestamp() if step.started_at else step.created_at.timestamp(),
                finished_at=step.finished_at.timestamp() if step.finished_at else None,
            )
            task_log.steps.append(step_log)
        
        return task_log

    def get_all_task_logs(self) -> List[TaskLog]:
        """
        获取当前 logger 中记录的所有任务日志
        
        注意：由于使用数据库，这里返回最近的任务日志（限制数量）
        """
        # 简化实现：只返回内存索引中的任务
        logs = []
        for task_id in self._task_run_map.values():
            log = self.get_task_log(task_id)
            if log:
                logs.append(log)
        
        return logs

    def _serialize_output(self, output: Any) -> dict:
        """序列化输出结果为 JSON 兼容的 dict"""
        if output is None:
            return {"type": "none", "value": None}
        
        if isinstance(output, (str, int, float, bool)):
            return {"type": type(output).__name__, "value": output}
        
        if isinstance(output, dict):
            return {"type": "dict", "value": output}
        
        if isinstance(output, list):
            return {"type": "list", "value": output}
        
        # 其他类型：转为字符串
        return {"type": "object", "value": str(output)}


# 工厂函数
def create_default_logger():
    """
    runtime 默认使用的 logger
    以后如果想换成文件/DB 实现，只要改这里即可
    """
    return DatabaseStepLogger()

