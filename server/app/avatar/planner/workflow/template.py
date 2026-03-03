"""
Workflow Template: 工作流模板定义和管理

工作流 = 多个阶段（Stage）的组合
每个阶段可以是：
- ai_task: 由AI动态规划的任务
- fixed_task: 预定义步骤的固定任务
- manual: 需要人工介入
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)
import yaml
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
from pathlib import Path


class StageType(str, Enum):
    """阶段类型"""
    AI_TASK = "ai_task"  # AI动态规划的任务
    FIXED_TASK = "fixed_task"  # 预定义步骤的固定任务
    MANUAL = "manual"  # 需要人工介入
    CONDITIONAL = "conditional"  # 条件分支


@dataclass
class WorkflowStage:
    """
    工作流阶段：工作流的基本执行单元
    
    类似 SubTask，但是更偏向模板化和可重用性
    """
    
    id: str
    name: str
    type: StageType
    
    # 目标和配置
    goal: Optional[str] = None  # ai_task 类型使用
    steps: List[Dict[str, Any]] = field(default_factory=list)  # fixed_task 类型使用
    
    # 依赖和流程控制
    depends_on: List[str] = field(default_factory=list)
    condition: Optional[str] = None  # 条件表达式（Python表达式）
    
    # 输入输出
    inputs: Dict[str, Any] = field(default_factory=dict)
    expected_outputs: List[str] = field(default_factory=list)
    
    # 执行配置
    timeout: int = 3600  # 超时时间（秒）
    max_retry: int = 1  # 重试次数
    on_failure: str = "stop"  # 失败处理：stop, continue, skip
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "goal": self.goal,
            "steps": self.steps,
            "depends_on": self.depends_on,
            "condition": self.condition,
            "inputs": self.inputs,
            "expected_outputs": self.expected_outputs,
            "timeout": self.timeout,
            "max_retry": self.max_retry,
            "on_failure": self.on_failure,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkflowStage:
        stage_type = data.get("type", "ai_task")
        if isinstance(stage_type, str):
            stage_type = StageType(stage_type)
        
        return cls(
            id=data["id"],
            name=data["name"],
            type=stage_type,
            goal=data.get("goal"),
            steps=data.get("steps", []),
            depends_on=data.get("depends_on", []),
            condition=data.get("condition"),
            inputs=data.get("inputs", {}),
            expected_outputs=data.get("expected_outputs", []),
            timeout=data.get("timeout", 3600),
            max_retry=data.get("max_retry", 1),
            on_failure=data.get("on_failure", "stop"),
            metadata=data.get("metadata", {})
        )


@dataclass
class WorkflowTemplate:
    """
    工作流模板：定义可重复执行的自动化流程
    
    支持：
    - 定时触发（Cron表达式）
    - 手动触发
    - 事件触发（未来扩展）
    """
    
    id: str
    name: str
    description: str = ""
    
    # 触发配置
    schedule: Optional[str] = None  # Cron表达式，例如 "0 8 * * *" (每天8点)
    enabled: bool = True
    
    # 阶段定义
    stages: List[WorkflowStage] = field(default_factory=list)
    
    # 全局配置
    timeout: int = 7200  # 整个工作流超时（秒）
    max_retries: int = 0  # 工作流级别重试
    
    # 错误处理
    on_failure: str = "notify"  # notify, retry, ignore
    notify_on_success: bool = False
    notify_on_failure: bool = True
    
    # 输入参数（运行时可覆盖）
    default_inputs: Dict[str, Any] = field(default_factory=dict)
    
    # 元数据
    tags: List[str] = field(default_factory=list)
    category: str = "general"
    version: str = "1.0"
    author: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_stage(self, stage: WorkflowStage) -> None:
        """添加阶段"""
        self.stages.append(stage)
    
    def get_stage(self, stage_id: str) -> Optional[WorkflowStage]:
        """根据ID获取阶段"""
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        return None
    
    def validate(self) -> tuple[bool, Optional[str]]:
        """
        验证模板的有效性
        
        返回: (是否有效, 错误信息)
        """
        # 检查阶段ID唯一性
        stage_ids = [s.id for s in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            return False, "Stage IDs must be unique"
        
        # 检查依赖关系是否有效
        for stage in self.stages:
            for dep_id in stage.depends_on:
                if dep_id not in stage_ids:
                    return False, f"Stage {stage.id} depends on non-existent stage {dep_id}"
        
        # 检查是否有循环依赖（简单检测）
        # TODO: 实现更完整的循环检测
        
        # 检查 Cron 表达式
        if self.schedule:
            try:
                from croniter import croniter
                if not croniter.is_valid(self.schedule):
                    return False, f"Invalid cron expression: {self.schedule}"
            except ImportError:
                # 如果没有安装 croniter，跳过验证
                pass
        
        return True, None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "schedule": self.schedule,
            "enabled": self.enabled,
            "stages": [s.to_dict() for s in self.stages],
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "on_failure": self.on_failure,
            "notify_on_success": self.notify_on_success,
            "notify_on_failure": self.notify_on_failure,
            "default_inputs": self.default_inputs,
            "tags": self.tags,
            "category": self.category,
            "version": self.version,
            "author": self.author,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkflowTemplate:
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            schedule=data.get("schedule"),
            enabled=data.get("enabled", True),
            stages=[WorkflowStage.from_dict(s) for s in data.get("stages", [])],
            timeout=data.get("timeout", 7200),
            max_retries=data.get("max_retries", 0),
            on_failure=data.get("on_failure", "notify"),
            notify_on_success=data.get("notify_on_success", False),
            notify_on_failure=data.get("notify_on_failure", True),
            default_inputs=data.get("default_inputs", {}),
            tags=data.get("tags", []),
            category=data.get("category", "general"),
            version=data.get("version", "1.0"),
            author=data.get("author"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            metadata=data.get("metadata", {})
        )
    
    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON 字符串"""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> WorkflowTemplate:
        """从 JSON 字符串加载"""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def to_yaml(self) -> str:
        """导出为 YAML 字符串"""
        return yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False)
    
    @classmethod
    def from_yaml(cls, yaml_str: str) -> WorkflowTemplate:
        """从 YAML 字符串加载"""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)
    
    def save_to_file(self, file_path: str) -> None:
        """保存到文件（自动识别 JSON/YAML）"""
        path = Path(file_path)
        
        if path.suffix in ['.yaml', '.yml']:
            content = self.to_yaml()
        else:
            content = self.to_json()
        
        path.write_text(content, encoding='utf-8')
    
    @classmethod
    def load_from_file(cls, file_path: str) -> WorkflowTemplate:
        """从文件加载（自动识别 JSON/YAML）"""
        path = Path(file_path)
        content = path.read_text(encoding='utf-8')
        
        if path.suffix in ['.yaml', '.yml']:
            return cls.from_yaml(content)
        else:
            return cls.from_json(content)


class WorkflowTemplateManager:
    """
    工作流模板管理器
    
    负责：
    - 模板的增删改查
    - 模板的持久化
    - 模板的验证
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._storage_path = Path(storage_path) if storage_path else None
        
        if self._storage_path and self._storage_path.exists():
            self._load_all_templates()
    
    def register(self, template: WorkflowTemplate) -> None:
        """注册模板"""
        # 验证模板
        is_valid, error = template.validate()
        if not is_valid:
            raise ValueError(f"Invalid template: {error}")
        
        self._templates[template.id] = template
        
        # 持久化
        if self._storage_path:
            self._save_template(template)
    
    def get(self, template_id: str) -> Optional[WorkflowTemplate]:
        """获取模板"""
        return self._templates.get(template_id)
    
    def list(self, category: Optional[str] = None, tags: Optional[List[str]] = None) -> List[WorkflowTemplate]:
        """列出所有模板（支持过滤）"""
        templates = list(self._templates.values())
        
        if category:
            templates = [t for t in templates if t.category == category]
        
        if tags:
            templates = [t for t in templates if any(tag in t.tags for tag in tags)]
        
        return templates
    
    def delete(self, template_id: str) -> bool:
        """删除模板"""
        if template_id in self._templates:
            del self._templates[template_id]
            
            # 删除文件
            if self._storage_path:
                file_path = self._storage_path / f"{template_id}.json"
                if file_path.exists():
                    file_path.unlink()
            
            return True
        return False
    
    def _save_template(self, template: WorkflowTemplate) -> None:
        """保存模板到文件"""
        if not self._storage_path:
            return
        
        self._storage_path.mkdir(parents=True, exist_ok=True)
        file_path = self._storage_path / f"{template.id}.json"
        template.save_to_file(str(file_path))
    
    def _load_all_templates(self) -> None:
        """加载所有模板"""
        if not self._storage_path or not self._storage_path.exists():
            return
        
        for file_path in self._storage_path.glob("*.json"):
            try:
                template = WorkflowTemplate.load_from_file(str(file_path))
                self._templates[template.id] = template
            except Exception as e:
                logger.error(f"Failed to load template from {file_path}: {e}")
