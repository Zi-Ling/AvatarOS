"""
DurableInterruptSignal — 持久化中断信号。

在审批等待或暂停时 raise 此异常，GraphController 捕获后安全退出执行循环。
执行流程完全退出，不占用协程或 worker 资源。
恢复由 RecoveryEngine 在审批通过/用户恢复时触发。
"""


class DurableInterruptSignal(Exception):
    """
    持久化中断信号。

    Attributes:
        reason: 中断原因（waiting_approval / paused / manual_stop）
        task_id: 关联的任务 ID（可选）
        checkpoint_id: 中断时创建的 Checkpoint ID（可选）
    """

    def __init__(
        self,
        reason: str = "waiting_approval",
        task_id: str | None = None,
        checkpoint_id: str | None = None,
    ):
        self.reason = reason
        self.task_id = task_id
        self.checkpoint_id = checkpoint_id
        super().__init__(f"DurableInterrupt: {reason}")
