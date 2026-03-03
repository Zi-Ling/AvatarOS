"""
Input Resolver

Resolves stage inputs by replacing references to other stages' outputs.
"""
from __future__ import annotations

import re
from typing import Any, Dict

from ..models import WorkflowRun


class InputResolver:
    """
    输入解析器
    
    解析阶段输入（替换引用）
    
    支持格式：
    - "{{stage_1.output_name}}"
    - "{{inputs.param_name}}"
    """
    
    # 引用模式: {{source.field}}
    REF_PATTERN = re.compile(r'\{\{\s*(\w+)\.(\w+)\s*\}\}')
    
    @staticmethod
    def resolve(
        stage_inputs: Dict[str, Any],
        run: WorkflowRun
    ) -> Dict[str, Any]:
        """
        解析阶段输入
        
        Args:
            stage_inputs: 阶段原始输入
            run: WorkflowRun 对象
            
        Returns:
            解析后的输入
        """
        resolved = stage_inputs.copy()
        
        for key, value in list(resolved.items()):
            if isinstance(value, str):
                matches = InputResolver.REF_PATTERN.findall(value)
                
                if matches:
                    # 完整替换（保留类型）
                    if len(matches) == 1 and \
                       value.strip() == f"{{{{ {matches[0][0]}.{matches[0][1]} }}}}".replace(" ", ""):
                        
                        source, var_name = matches[0]
                        
                        if source == "inputs":
                            resolved[key] = run.inputs.get(var_name)
                        else:
                            # 从其他阶段获取输出
                            source_run = run.get_stage_run(source)
                            if source_run:
                                resolved[key] = source_run.outputs.get(var_name)
                    else:
                        # 部分替换（字符串插值）
                        def replace_ref(match):
                            source, var_name = match.groups()
                            
                            if source == "inputs":
                                val = run.inputs.get(var_name)
                            else:
                                source_run = run.get_stage_run(source)
                                val = source_run.outputs.get(var_name) if source_run else None
                            
                            return str(val) if val is not None else match.group(0)
                        
                        resolved[key] = InputResolver.REF_PATTERN.sub(replace_ref, value)
        
        return resolved

