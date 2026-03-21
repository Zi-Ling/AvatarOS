"""
ObjectRegistry — 业务对象元数据注册表

运行时单例，管理所有已注册 Business_Object 的元数据。
注册时自动合并 BASE_FIELDS，校验字段完整性。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .models import (
    BASE_FIELDS,
    FieldDefinition,
    FieldType,
    ObjectDefinition,
    RelationConstraint,
    DuplicateObjectError,
    ReadonlyFieldError,
)

logger = logging.getLogger(__name__)


class ObjectRegistry:
    """业务对象元数据注册表"""

    def __init__(self) -> None:
        self._objects: dict[str, ObjectDefinition] = {}
        # 缓存：对象名 → 合并后的全部字段（基础 + 业务）
        self._all_fields: dict[str, list[FieldDefinition]] = {}

    def register(self, definition: ObjectDefinition) -> None:
        """注册业务对象定义，验证字段完整性，重复名称抛出 DuplicateObjectError"""
        name = definition.name
        if name in self._objects:
            raise DuplicateObjectError(f"对象名称重复: {name}")

        # 验证字段定义完整性
        for f in definition.fields:
            if f.field_type == FieldType.ENUM and not f.enum_values:
                raise ValueError(f"枚举字段 {f.name} 缺少 enum_values")
            if f.field_type == FieldType.REFERENCE and not f.reference_to:
                raise ValueError(f"引用字段 {f.name} 缺少 reference_to")
            if f.field_type == FieldType.COMPUTED and not f.compute_key:
                raise ValueError(f"派生字段 {f.name} 缺少 compute_key")
            if f.field_type == FieldType.COMPUTED:
                f.readonly = True  # 强制只读

        self._objects[name] = definition
        # 合并基础字段 + 业务字段（排除 COMPUTED，它们不存储）
        self._all_fields[name] = list(BASE_FIELDS) + definition.fields
        logger.info(f"注册业务对象: {name} ({len(definition.fields)} 个业务字段)")

    def get(self, object_type: str) -> ObjectDefinition | None:
        """按名称查询对象定义"""
        return self._objects.get(object_type)

    def list_all(self) -> list[ObjectDefinition]:
        """返回所有已注册对象定义"""
        return list(self._objects.values())

    def get_all_fields(self, object_type: str) -> list[FieldDefinition]:
        """返回对象的全部字段（基础 + 业务，含 COMPUTED）"""
        return self._all_fields.get(object_type, [])

    def get_storage_fields(self, object_type: str) -> list[FieldDefinition]:
        """返回对象的存储字段（基础 + 业务，排除 COMPUTED）"""
        return [f for f in self.get_all_fields(object_type) if f.field_type != FieldType.COMPUTED]

    def validate_fields(self, object_type: str, fields: dict[str, Any]) -> list[str]:
        """校验字段值合法性，返回错误列表（空列表表示通过）"""
        defn = self._objects.get(object_type)
        if not defn:
            return [f"对象类型不存在: {object_type}"]

        errors: list[str] = []
        all_fields = {f.name: f for f in self.get_all_fields(object_type)}

        for field_name, value in fields.items():
            fd = all_fields.get(field_name)
            if not fd:
                errors.append(f"未知字段: {field_name}")
                continue
            if fd.readonly or fd.field_type == FieldType.COMPUTED:
                errors.append(f"只读字段不可修改: {field_name}")
                continue
            if fd.deprecated:
                errors.append(f"字段已废弃: {field_name}")
                continue
            if fd.field_type == FieldType.ENUM and fd.enum_values and value is not None:
                if value not in fd.enum_values:
                    errors.append(f"字段 {field_name} 值 '{value}' 不在枚举范围 {fd.enum_values}")

        # 检查必填字段
        for fd in defn.fields:
            if fd.required and fd.name not in fields:
                # 基础字段由系统自动填充，只检查业务字段
                if fd.field_type != FieldType.COMPUTED:
                    errors.append(f"必填字段缺失: {fd.name}")

        return errors

    def get_text_fields(self, object_type: str) -> list[str]:
        """返回指定对象的所有文本类型字段名（用于关键词搜索）"""
        return [
            f.name
            for f in self.get_all_fields(object_type)
            if f.field_type == FieldType.TEXT and not f.deprecated
        ]

    def get_allowed_relations(self, object_type: str) -> list[RelationConstraint]:
        """返回该对象允许的关联关系约束"""
        defn = self._objects.get(object_type)
        return defn.allowed_relations if defn else []

    def get_computed_fields(self, object_type: str) -> list[FieldDefinition]:
        """返回对象的派生字段列表"""
        return [
            f for f in self.get_all_fields(object_type)
            if f.field_type == FieldType.COMPUTED
        ]

    def has_field(self, object_type: str, field_name: str) -> bool:
        """检查对象是否包含指定字段"""
        return any(f.name == field_name for f in self.get_all_fields(object_type))

    # ── 动态对象管理 ──

    def register_dynamic(self, definition: ObjectDefinition) -> None:
        """注册动态对象定义（允许覆盖已有动态对象以支持 alter）"""
        name = definition.name
        existing = self._objects.get(name)
        if existing is not None and not getattr(existing, '_is_dynamic', False):
            raise DuplicateObjectError(f"不能覆盖内置对象: {name}")

        # 验证字段完整性（同 register）
        for f in definition.fields:
            if f.field_type == FieldType.ENUM and not f.enum_values:
                raise ValueError(f"枚举字段 {f.name} 缺少 enum_values")
            if f.field_type == FieldType.REFERENCE and not f.reference_to:
                raise ValueError(f"引用字段 {f.name} 缺少 reference_to")
            if f.field_type == FieldType.COMPUTED and not f.compute_key:
                raise ValueError(f"派生字段 {f.name} 缺少 compute_key")
            if f.field_type == FieldType.COMPUTED:
                f.readonly = True

        definition._is_dynamic = True  # type: ignore[attr-defined]
        self._objects[name] = definition
        self._all_fields[name] = list(BASE_FIELDS) + definition.fields
        logger.info(f"注册动态对象: {name} ({len(definition.fields)} 个业务字段)")

    def unregister(self, object_type: str) -> bool:
        """注销动态对象（仅允许注销动态对象）"""
        existing = self._objects.get(object_type)
        if existing is None:
            return False
        if not getattr(existing, '_is_dynamic', False):
            raise DuplicateObjectError(f"不能注销内置对象: {object_type}")
        del self._objects[object_type]
        self._all_fields.pop(object_type, None)
        logger.info(f"注销动态对象: {object_type}")
        return True

    def is_dynamic(self, object_type: str) -> bool:
        """检查对象是否为动态定义"""
        defn = self._objects.get(object_type)
        return getattr(defn, '_is_dynamic', False) if defn else False
