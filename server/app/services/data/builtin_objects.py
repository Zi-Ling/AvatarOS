"""
MVP 预置业务对象定义

Contact、Task、Activity 三个核心对象。
Document 后置到下一阶段（与 artifact 绑定复杂度高）。
"""

from __future__ import annotations

from .models import FieldDefinition, FieldType, ObjectDefinition, RelationConstraint
from .registry import ObjectRegistry


CONTACT_DEFINITION = ObjectDefinition(
    name="Contact",
    description="联系人/客户，承载客户关系管理的核心对象",
    schema_version=1,
    fields=[
        FieldDefinition(name="name", field_type=FieldType.TEXT, required=True),
        FieldDefinition(name="phone", field_type=FieldType.TEXT),
        FieldDefinition(name="email", field_type=FieldType.TEXT),
        FieldDefinition(name="company", field_type=FieldType.TEXT),
        FieldDefinition(
            name="priority", field_type=FieldType.ENUM,
            enum_values=["low", "medium", "high"],
        ),
        FieldDefinition(
            name="stage", field_type=FieldType.ENUM,
            enum_values=["lead", "prospect", "customer", "churned"],
        ),
        FieldDefinition(name="source", field_type=FieldType.TEXT),
        FieldDefinition(name="notes", field_type=FieldType.TEXT),
        FieldDefinition(name="tags", field_type=FieldType.TEXT),  # JSON array
        # 派生字段
        FieldDefinition(
            name="last_activity_at", field_type=FieldType.COMPUTED,
            readonly=True, compute_key="contact_last_activity_at",
        ),
        FieldDefinition(
            name="open_task_count", field_type=FieldType.COMPUTED,
            readonly=True, compute_key="contact_open_task_count",
        ),
    ],
    allowed_relations=[
        RelationConstraint(relation_type="related_to", target_type="Activity", description="联系人的跟进活动"),
        RelationConstraint(relation_type="related_to", target_type="Task", description="联系人关联的任务"),
    ],
)


TASK_DEFINITION = ObjectDefinition(
    name="Task",
    description="任务/待办，承载跟进计划、会议安排等工作项",
    schema_version=1,
    fields=[
        FieldDefinition(name="title", field_type=FieldType.TEXT, required=True),
        FieldDefinition(name="description", field_type=FieldType.TEXT),
        FieldDefinition(name="due_date", field_type=FieldType.DATETIME),
        FieldDefinition(
            name="priority", field_type=FieldType.ENUM,
            enum_values=["low", "medium", "high"],
        ),
        FieldDefinition(
            name="task_type", field_type=FieldType.ENUM,
            enum_values=["follow_up", "call", "meeting", "email", "other"],
        ),
        FieldDefinition(name="assigned_to", field_type=FieldType.TEXT),
        FieldDefinition(
            name="related_contact_id", field_type=FieldType.REFERENCE,
            reference_to="Contact",
        ),
    ],
    allowed_relations=[
        RelationConstraint(relation_type="assigned_to", target_type="Contact", description="任务分配给联系人"),
        RelationConstraint(relation_type="depends_on", target_type="Task", description="任务依赖关系"),
    ],
)


ACTIVITY_DEFINITION = ObjectDefinition(
    name="Activity",
    description="活动记录，统一承载跟进、通话、会议、状态变化、AI 动作摘要等",
    schema_version=1,
    fields=[
        FieldDefinition(
            name="activity_type", field_type=FieldType.ENUM, required=True,
            enum_values=["follow_up", "call_log", "meeting_note", "status_change",
                         "system_action", "ai_summary", "other"],
        ),
        FieldDefinition(name="summary", field_type=FieldType.TEXT, required=True),
        FieldDefinition(name="detail", field_type=FieldType.TEXT),
        FieldDefinition(name="occurred_at", field_type=FieldType.DATETIME),
        FieldDefinition(
            name="related_contact_id", field_type=FieldType.REFERENCE,
            reference_to="Contact",
        ),
        FieldDefinition(
            name="related_task_id", field_type=FieldType.REFERENCE,
            reference_to="Task",
        ),
        FieldDefinition(name="actor", field_type=FieldType.TEXT),
    ],
    allowed_relations=[
        RelationConstraint(relation_type="related_to", target_type="Contact", description="活动关联的联系人"),
        RelationConstraint(relation_type="related_to", target_type="Task", description="活动关联的任务"),
    ],
)


ALL_BUILTIN_OBJECTS = [CONTACT_DEFINITION, TASK_DEFINITION, ACTIVITY_DEFINITION]


def register_builtin_objects(registry: ObjectRegistry) -> None:
    """批量注册 MVP 预置业务对象"""
    for defn in ALL_BUILTIN_OBJECTS:
        registry.register(defn)
