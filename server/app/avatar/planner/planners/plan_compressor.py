# server/app/avatar/planner/planners/plan_compressor.py

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class PlanCompressor:
    """
    计划压缩器
    
    自动检测并合并重复的 fs.* 操作，避免 LLM 生成过多重复步骤。
    
    规则：
    - 当检测到 3+ 个连续的相同类型 fs.* 操作时，建议合并为 python.run
    - 保持计划的语义不变
    """
    
    def __init__(self, threshold: int = 3):
        """
        Args:
            threshold: 触发压缩的重复操作阈值（默认3）
        """
        self.threshold = threshold
    
    def compress(self, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        压缩计划步骤
        
        Args:
            steps: 原始步骤列表
        
        Returns:
            压缩后的步骤列表
        """
        if not steps or len(steps) < self.threshold:
            return steps
        
        # 检测重复的 fs.* 操作
        repeated_groups = self._detect_repeated_fs_operations(steps)
        
        if not repeated_groups:
            return steps
        
        # 记录警告
        for group in repeated_groups:
            logger.warning(
                f"Detected {len(group['steps'])} repeated {group['operation']} operations. "
                f"Consider using python.run for batch processing."
            )
        
        # 暂时只记录警告，不自动重写（避免破坏计划）
        # 未来可以实现自动重写逻辑
        return steps
    
    def _detect_repeated_fs_operations(
        self,
        steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        检测重复的 fs.* 操作
        
        Returns:
            重复操作组列表，每组包含：
            - operation: 操作类型（如 fs.move）
            - steps: 重复的步骤列表
            - indices: 步骤索引列表
        """
        groups = []
        current_group = None
        
        for i, step in enumerate(steps):
            skill = step.get('skill', '')
            
            # 只关注 fs.* 操作
            if not skill.startswith('fs.'):
                # 结束当前组
                if current_group and len(current_group['steps']) >= self.threshold:
                    groups.append(current_group)
                current_group = None
                continue
            
            # 开始新组或继续当前组
            if current_group is None:
                current_group = {
                    'operation': skill,
                    'steps': [step],
                    'indices': [i]
                }
            elif current_group['operation'] == skill:
                # 相同操作，加入当前组
                current_group['steps'].append(step)
                current_group['indices'].append(i)
            else:
                # 不同操作，结束当前组
                if len(current_group['steps']) >= self.threshold:
                    groups.append(current_group)
                
                # 开始新组
                current_group = {
                    'operation': skill,
                    'steps': [step],
                    'indices': [i]
                }
        
        # 处理最后一组
        if current_group and len(current_group['steps']) >= self.threshold:
            groups.append(current_group)
        
        return groups
    
    def suggest_python_replacement(
        self,
        operation: str,
        steps: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        为重复操作生成 python.run 替代代码建议
        
        Args:
            operation: 操作类型（如 fs.move）
            steps: 重复的步骤列表
        
        Returns:
            Python 代码建议（如果适用）
        """
        if operation == 'fs.move':
            return self._suggest_batch_move(steps)
        elif operation == 'fs.copy':
            return self._suggest_batch_copy(steps)
        elif operation == 'fs.delete':
            return self._suggest_batch_delete(steps)
        else:
            return None
    
    def _suggest_batch_move(self, steps: List[Dict[str, Any]]) -> str:
        """生成批量移动的 python 代码"""
        moves = []
        for step in steps:
            params = step.get('params', {})
            src = params.get('src', '')
            dst = params.get('dst', '')
            if src and dst:
                moves.append(f"    os.rename('{src}', '{dst}')")
        
        code = "import os\n" + "\n".join(moves) + "\nprint('Batch move completed')"
        return code
    
    def _suggest_batch_copy(self, steps: List[Dict[str, Any]]) -> str:
        """生成批量复制的 python 代码"""
        copies = []
        for step in steps:
            params = step.get('params', {})
            src = params.get('src', '')
            dst = params.get('dst', '')
            if src and dst:
                copies.append(f"    shutil.copy2('{src}', '{dst}')")
        
        code = "import shutil\n" + "\n".join(copies) + "\nprint('Batch copy completed')"
        return code
    
    def _suggest_batch_delete(self, steps: List[Dict[str, Any]]) -> str:
        """生成批量删除的 python 代码"""
        deletes = []
        for step in steps:
            params = step.get('params', {})
            path = params.get('path', '')
            if path:
                deletes.append(f"    os.remove('{path}')")
        
        code = "import os\n" + "\n".join(deletes) + "\nprint('Batch delete completed')"
        return code


# 全局单例
_plan_compressor: Optional[PlanCompressor] = None


def get_plan_compressor() -> PlanCompressor:
    """获取全局 PlanCompressor 实例"""
    global _plan_compressor
    if _plan_compressor is None:
        _plan_compressor = PlanCompressor()
    return _plan_compressor
