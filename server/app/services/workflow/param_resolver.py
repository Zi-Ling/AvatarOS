# server/app/services/workflow/param_resolver.py
"""
参数占位符替换 + 类型校验。

正确性属性 P3：所有占位符在实例化后都被替换（无残留占位符）。
"""
from __future__ import annotations

import copy
import re
from typing import Any

from .models import WorkflowParamDef, WorkflowStepDef


class ParamValidationError(Exception):
    """参数校验失败"""

    def __init__(self, message: str, param_name: str = "", expected_type: str = ""):
        self.param_name = param_name
        self.expected_type = expected_type
        super().__init__(message)


class ParamResolver:
    """参数占位符替换 + 类型校验"""

    PLACEHOLDER_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def resolve(
        self,
        steps: list[WorkflowStepDef],
        param_defs: list[WorkflowParamDef],
        user_params: dict[str, Any],
    ) -> list[WorkflowStepDef]:
        """
        替换占位符并校验参数。

        1. 校验 required 参数都已提供
        2. 填充 default 值
        3. 类型校验
        4. 遍历所有 step.params，替换 {{placeholder}}
        5. 扫描替换后的结果，确认无残留占位符（P3）
        6. 返回替换后的 steps 副本
        """
        resolved_params = self._build_resolved_params(param_defs, user_params)
        result: list[WorkflowStepDef] = []
        for step in steps:
            new_params = self._replace_placeholders(
                copy.deepcopy(step.params), resolved_params
            )
            residual = self._scan_residual(new_params)
            if residual:
                raise ParamValidationError(
                    f"步骤 {step.step_id} 中存在未替换的占位符: {residual}",
                    param_name=", ".join(residual),
                )
            result.append(step.model_copy(update={"params": new_params}))
        return result

    def _build_resolved_params(
        self,
        param_defs: list[WorkflowParamDef],
        user_params: dict[str, Any],
    ) -> dict[str, Any]:
        """校验 required + 填充 default + 类型校验，返回最终参数字典。"""
        resolved: dict[str, Any] = {}
        for pdef in param_defs:
            if pdef.name in user_params:
                value = self._validate_type(
                    pdef.name, user_params[pdef.name], pdef.type
                )
                resolved[pdef.name] = value
            elif pdef.default is not None:
                resolved[pdef.name] = pdef.default
            elif pdef.required:
                raise ParamValidationError(
                    f"缺少必需参数: {pdef.name}",
                    param_name=pdef.name,
                    expected_type=pdef.type,
                )
        return resolved

    def _validate_type(self, name: str, value: Any, expected_type: str) -> Any:
        """类型校验 + 强制转换。"""
        if expected_type == "string":
            return str(value)
        elif expected_type == "number":
            try:
                if isinstance(value, float) or "." in str(value):
                    return float(value)
                return int(value)
            except (ValueError, TypeError):
                raise ParamValidationError(
                    f"参数 {name} 期望 number 类型，实际值: {value!r}",
                    param_name=name,
                    expected_type=expected_type,
                )
        elif expected_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                if value.lower() in ("true", "1", "yes"):
                    return True
                if value.lower() in ("false", "0", "no"):
                    return False
            raise ParamValidationError(
                f"参数 {name} 期望 boolean 类型，实际值: {value!r}",
                param_name=name,
                expected_type=expected_type,
            )
        elif expected_type == "file_path":
            s = str(value)
            if not s:
                raise ParamValidationError(
                    f"参数 {name} 期望非空 file_path",
                    param_name=name,
                    expected_type=expected_type,
                )
            return s
        return value

    def _replace_placeholders(
        self, obj: Any, params: dict[str, Any]
    ) -> Any:
        """递归替换 dict/list/str 中的 {{placeholder}}。"""
        if isinstance(obj, str):
            # 完整匹配：整个字符串就是一个占位符 → 保留原始类型
            full_match = re.fullmatch(r"\{\{(\w+)\}\}", obj)
            if full_match and full_match.group(1) in params:
                return params[full_match.group(1)]
            # 部分匹配：字符串中嵌入占位符 → 字符串替换
            return self.PLACEHOLDER_PATTERN.sub(
                lambda m: str(params.get(m.group(1), m.group(0))), obj
            )
        elif isinstance(obj, dict):
            return {k: self._replace_placeholders(v, params) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._replace_placeholders(item, params) for item in obj]
        return obj

    def _scan_residual(self, obj: Any) -> list[str]:
        """递归扫描残留占位符，返回未替换的占位符名列表。"""
        found: list[str] = []
        if isinstance(obj, str):
            found.extend(self.PLACEHOLDER_PATTERN.findall(obj))
        elif isinstance(obj, dict):
            for v in obj.values():
                found.extend(self._scan_residual(v))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(self._scan_residual(item))
        return found
