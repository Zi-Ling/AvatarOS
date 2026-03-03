from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.planner.models import Task, Step

class ContextManager:
    """
    负责管理和压缩任务执行的上下文 (Task History)，
    防止 Prompt Token 爆炸。
    """

    def __init__(self, max_history_steps: int = 5, max_output_chars: int = 1000):
        self.max_history_steps = max_history_steps
        self.max_output_chars = max_output_chars

    def prune_task_for_replanning(self, task: Task) -> Task:
        """
        创建一个 Task 的"瘦身版"副本，用于 Re-planning。
        
        策略：
        1. 保留所有 PENDING/RUNNING/FAILED 的步骤（未完成的）。
        2. 保留最近 N 个 SUCCESS 的步骤的完整 Result。
        3. 对于更早的 SUCCESS 步骤，丢弃 Result.output，只保留 Status="SUCCESS" 和摘要。
        """
        # 我们不修改原始 task，而是构建一个 Prompt 友好的视图
        # 但为了简单，我们这里直接修改 Task 对象的副本或返回一个新的轻量级对象
        # 由于 SimpleLLMPlanner 用 Task.to_dict() 或 prompt builder 读数据，
        # 我们最好返回一个 proxy object 或者直接修改副本。
        
        # 这里演示：直接清理 task.steps 中的 result 数据
        # 注意：这会丢失原始数据，所以调用者必须传入副本，或者我们只返回 dict。
        
        # 为了不破坏原始 task（可能用于审计），我们这里不做深拷贝（太贵），
        # 而是返回一个专门给 Prompt 用的 Summary List。
        pass

    def get_history_summary(self, task: Task) -> List[Dict[str, Any]]:
        """
        生成给 LLM 看的执行历史摘要。
        """
        summary = []
        
        # 筛选出已执行的步骤
        executed_steps = [s for s in task.steps if s.status.name in ("SUCCESS", "FAILED", "SKIPPED")]
        
        # 只要最近 N 个 + 所有 FAILED 的
        # 其实 FAILED 的通常是最后一个
        
        count = len(executed_steps)
        
        for i, step in enumerate(executed_steps):
            is_recent = (i >= count - self.max_history_steps)
            is_failed = (step.status.name == "FAILED")
            
            item = {
                "id": step.id,
                "skill": step.skill_name,
                "status": step.status.name,
                "params": step.params,
            }
            
            if step.result:
                # 错误信息总是保留
                if step.result.error:
                    item["error"] = step.result.error
                
                # Output: 只有最近的或失败的才保留，且截断
                if (is_recent or is_failed) and step.result.output is not None:
                    output_str = str(step.result.output)
                    if len(output_str) > self.max_output_chars:
                        item["output"] = output_str[:self.max_output_chars] + "...(truncated)"
                    else:
                        item["output"] = output_str
                else:
                    # 旧的成功步骤，省略 output
                    item["output"] = "(omitted for brevity)"
            
            summary.append(item)
            
        return summary

