# app/avatar/learning/manager.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import (
    LearningContext,
    LearningExample,
    LearningModule,
    LearningResult,
)
from ..memory.manager import MemoryManager
from .knowledge.document_kb import DocumentKnowledgeBase

import logging

logger = logging.getLogger(__name__)


@dataclass
class LearningManagerConfig:
    """
    LearningManager 的配置：
    - workspace_root: 学习模块可以使用的工作目录（例如存缓存/模型）
    - enable_document_kb: 是否启用文档知识库
    """

    workspace_root: Optional[Path] = None
    enable_document_kb: bool = True


class LearningManager:
    """
    统一管理多个 LearningModule，并提供与 Avatar 对接的高层接口：

    - register(module) ：注册具体 learner
    - learn_from_example(...) ：手动喂一个样本给所有 learner

    - on_task_finished(...) ：在任务执行完成后调用
    - on_skill_event(...)   ：在技能执行后调用
    """

    def __init__(
        self,
        config: Optional[LearningManagerConfig] = None,
        memory_manager: Optional[MemoryManager] = None,
    ) -> None:
        self._modules: Dict[str, LearningModule] = {}
        self._config = config or LearningManagerConfig()
        self._memory_manager = memory_manager
        
        # 初始化文档知识库（Learning 层的业务模块）
        self._document_kb: Optional[DocumentKnowledgeBase] = None
        logger.debug(f"Initializing Document KB (enabled={self._config.enable_document_kb}, workspace={self._config.workspace_root})")
        
        if self._config.enable_document_kb and self._config.workspace_root:
            try:
                kb_dir = self._config.workspace_root / "document_kb"
                self._document_kb = DocumentKnowledgeBase(kb_dir)
                logger.info(f"Document Knowledge Base initialized at {kb_dir}")
            except Exception as e:
                logger.error(f"Failed to initialize Document KB: {e}", exc_info=True)
                self._document_kb = None
        else:
            logger.debug("Document KB not enabled or workspace_root is None")

    # ------------------------------------------------------------------
    # 注册 / 列表
    # ------------------------------------------------------------------
    def register(self, module: LearningModule) -> None:
        if not module.name:
            raise ValueError("LearningModule.name 不能为空")
        self._modules[module.name] = module

    def list_modules(self) -> List[str]:
        return list(self._modules.keys())

    # ------------------------------------------------------------------
    # 底层接口：直接用 example + context 驱动所有 learner
    # ------------------------------------------------------------------
    def learn_from_example(
        self,
        example: LearningExample,
        *,
        ctx: LearningContext,
    ) -> Dict[str, LearningResult]:
        """
        把一条 LearningExample 广播给所有已注册的 LearningModule。
        返回各个模块的结果。
        """
        results: Dict[str, LearningResult] = {}
        for name, module in self._modules.items():
            try:
                result = module.learn(example, ctx=ctx)
            except Exception as e:  # noqa: BLE001
                result = LearningResult(
                    success=False,
                    message=f"exception: {e}",
                    data=None,
                )
            results[name] = result
        return results

    # ------------------------------------------------------------------
    # 高层 Hook：任务结束时调用
    # ------------------------------------------------------------------
    def on_task_finished(
        self,
        *,
        task_id: str,
        user_id: Optional[str],
        status: str,
        summary: str,
        extra: Optional[dict] = None,
    ) -> Dict[str, LearningResult]:
        """
        在 AvatarMain.run(...) 结束后调用：
        - 用于让学习模块“看一眼”任务结果，积累经验
        """
        workspace = (
            self._config.workspace_root / "tasks" / task_id
            if self._config.workspace_root
            else None
        )

        example = LearningExample(
            kind="task_finished",
            input_data={
                "task_id": task_id,
                "status": status,  # success / failed / cancelled ...
                "summary": summary,
                "extra": extra or {},
            },
            target=None,
            metadata={
                "user_id": user_id,
            },
        )

        ctx = LearningContext(
            workspace=workspace,
            user_id=user_id,
            task_id=task_id,
            memory=self._memory_manager,
            extra={},
        )

        return self.learn_from_example(example, ctx=ctx)

    # ------------------------------------------------------------------
    # 高层 Hook：技能执行后调用
    # ------------------------------------------------------------------
    def on_skill_event(
        self,
        *,
        skill_name: str,
        user_id: Optional[str],
        task_id: Optional[str],
        event_type: str,   # "usage" / "error" / "warning" ...
        status: str,       # "success" / "failed" ...
        detail: str,
        extra: Optional[dict] = None,
    ) -> Dict[str, LearningResult]:
        """
        在每次技能执行后调用：
        - 可以让学习模块积累“哪个技能在哪些参数下容易出错”等信息
        """
        workspace = (
            self._config.workspace_root / "skills" / skill_name
            if self._config.workspace_root
            else None
        )

        example = LearningExample(
            kind="skill_event",
            input_data={
                "skill_name": skill_name,
                "event_type": event_type,
                "status": status,
                "detail": detail,
                "extra": extra or {},
            },
            target=None,
            metadata={
                "user_id": user_id,
                "task_id": task_id,
            },
        )

        ctx = LearningContext(
            workspace=workspace,
            user_id=user_id,
            task_id=task_id,
            memory=self._memory_manager,
            extra={},
        )

        return self.learn_from_example(example, ctx=ctx)
    
    # =========================================================================
    # 对外业务接口：供 Planner / API 使用（完全重构新增）
    # =========================================================================
    
    def get_user_preferences(self, user_id: str = "default") -> Optional[Dict[str, Any]]:
        """
        获取用户偏好（对外接口）
        
        职责：
        1. 先从 UserPreferenceLearner 的内存缓存读取（快）
        2. 如果没有，从 Memory 读取（慢）
        
        返回示例：
        {
            "preferred_file_format": "excel",
            "user_level": "advanced",
            "preferred_language": "zh",
            "python_usage_count": 10
        }
        """
        # 1. 优先从内存缓存读取
        for module in self._modules.values():
            if module.name == "user_preference":
                prefs = module.get_prefs(user_id)
                if prefs:
                    return prefs
        
        # 2. 从 Memory 读取（如果缓存未命中）
        if self._memory_manager:
            return self._memory_manager.get_knowledge(f"user_prefs:{user_id}")
        
        return None
    
    def get_skill_statistics(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有技能的统计数据（对外接口）
        
        返回格式：
        {
            "python.run": {
                "total": 10,
                "success": 9,
                "failed": 1,
                "success_rate": 0.9,
                "last_error": None
            },
            ...
        }
        """
        # 从 SkillStatsLearner 的内存缓存读取
        for module in self._modules.values():
            if module.name == "skill_stats":
                stats_snapshot = module.stats_snapshot
                # 转换为字典格式
                result = {}
                for skill_name, stat in stats_snapshot.items():
                    result[skill_name] = {
                        "total": stat.total,
                        "success": stat.success,
                        "failed": stat.failed,
                        "success_rate": stat.success_rate,
                        "last_error": stat.last_error,
                    }
                return result
        
        return {}
    
    def get_skill_stat(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """
        获取单个技能的统计数据（对外接口）
        """
        all_stats = self.get_skill_statistics()
        return all_stats.get(skill_name)
    
    def get_user_preference(self, user_id: str, key: str, default=None):
        """
        获取单个用户偏好项（对外接口）
        
        示例:
            learning.get_user_preference("user123", "preferred_file_format", "csv")
            # 返回: "excel"
        """
        prefs = self.get_user_preferences(user_id)
        if prefs:
            return prefs.get(key, default)
        return default
    
    # =========================================================================
    # Document Knowledge Base API（完全重构新增）
    # =========================================================================
    
    @property
    def document_kb(self) -> Optional[DocumentKnowledgeBase]:
        """
        获取文档知识库实例（对外接口）
        
        返回:
            DocumentKnowledgeBase 实例，如果未启用则返回 None
        """
        return self._document_kb
    
    def has_document_kb(self) -> bool:
        """检查文档知识库是否可用"""
        return self._document_kb is not None
