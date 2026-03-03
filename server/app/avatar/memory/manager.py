# avatar/memory/manager.py
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, List

from .base import MemoryKind, MemoryRecord, MemoryStore
from .state.store import (
    InMemoryWorkingStateStore,
    JsonFileWorkingStateStore,
)
from .episodic.store import JsonlEpisodicMemoryStore
from .knowledge.store import JsonFileKnowledgeMemoryStore

import logging

logger = logging.getLogger(__name__)

# 向量存储（可选）
try:
    from .vector.store import ChromaVectorStore
    VECTOR_STORE_AVAILABLE = True
except ImportError:
    VECTOR_STORE_AVAILABLE = False
    ChromaVectorStore = None  # type: ignore


@dataclass
class MemoryManagerConfig:
    """
    MemoryManager 的配置：
    - root_dir: 所有本地持久化 memory 的根目录
    - use_inmemory_working_state: WorkingState 是否只用内存（开发/测试环境很有用）
    - enable_vector_store: 是否启用向量存储（需要安装 chromadb）
    """
    root_dir: Path
    use_inmemory_working_state: bool = True
    enable_vector_store: bool = True  # 默认启用向量存储


class MemoryManager:
    """
    MemoryManager 负责把三类记忆统一管理起来：
    - Working State  : 当前会话/任务的短期工作记忆
    - Episodic Memory: 事件/情节记忆（task run、skill 事件日志）
    - Knowledge      : 长期知识记忆（用户偏好、任务模板等）

    上层（Router / AvatarMain / Skills）只需要依赖这个类，
    不需要关心底层是 JSON 文件还是 DB。
    """

    def __init__(
        self,
        working_state_store: MemoryStore,
        episodic_store: MemoryStore,
        knowledge_store: MemoryStore,
        vector_store: Optional[Any] = None,  # ChromaVectorStore（可选）
    ) -> None:
        self._working_state_store = working_state_store
        self._episodic_store = episodic_store
        self._knowledge_store = knowledge_store
        self._vector_store = vector_store  # 向量存储

    # -------------------------------------------------------------------------
    # 工厂方法：从本地目录构造一个默认 MemoryManager
    # -------------------------------------------------------------------------
    @classmethod
    def from_local_dir(cls, config: MemoryManagerConfig) -> "MemoryManager":
        root = config.root_dir
        root.mkdir(parents=True, exist_ok=True)

        # Working State：默认用内存版本，必要时也可以换成 Json 版本
        if config.use_inmemory_working_state:
            working_state_store: MemoryStore = InMemoryWorkingStateStore()
        else:
            working_state_store = JsonFileWorkingStateStore(root / "working_state.json")

        # Episodic：事件日志，用 JSONL
        episodic_store: MemoryStore = JsonlEpisodicMemoryStore(root / "episodic.log")

        # Knowledge：长期知识，用 JSON 文件
        knowledge_store: MemoryStore = JsonFileKnowledgeMemoryStore(root / "knowledge.json")

        # Vector Store：向量存储（可选）
        vector_store = None
        if config.enable_vector_store and VECTOR_STORE_AVAILABLE and ChromaVectorStore:
            try:
                vector_store = ChromaVectorStore(
                    persist_directory=root / "vector_db",
                    collection_name="episodic_memory",
                )
                logger.info(f"Vector Store initialized at {root / 'vector_db'}")
            except Exception as e:
                logger.warning(f"Failed to initialize Vector Store: {e}")
                vector_store = None

        return cls(
            working_state_store=working_state_store,
            episodic_store=episodic_store,
            knowledge_store=knowledge_store,
            vector_store=vector_store,
        )

    # -------------------------------------------------------------------------
    # 通用底层接口（如果你想更灵活地操作）
    # -------------------------------------------------------------------------
    def save_record(self, record: MemoryRecord) -> None:
        if record.kind == MemoryKind.WORKING_STATE:
            self._working_state_store.save(record)
        elif record.kind == MemoryKind.EPISODIC:
            self._episodic_store.save(record)
        elif record.kind == MemoryKind.KNOWLEDGE:
            self._knowledge_store.save(record)
        else:
            raise ValueError(f"Unsupported MemoryKind: {record.kind}")

    def get_record(self, kind: MemoryKind, key: str) -> Optional[MemoryRecord]:
        if kind == MemoryKind.WORKING_STATE:
            return self._working_state_store.get(kind, key)
        elif kind == MemoryKind.EPISODIC:
            return self._episodic_store.get(kind, key)
        elif kind == MemoryKind.KNOWLEDGE:
            return self._knowledge_store.get(kind, key)
        else:
            return None

    def query_records(
        self,
        kind: MemoryKind,
        prefix: Optional[str] = None,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        if kind == MemoryKind.WORKING_STATE:
            return self._working_state_store.query(kind, prefix, limit)
        elif kind == MemoryKind.EPISODIC:
            return self._episodic_store.query(kind, prefix, limit)
        elif kind == MemoryKind.KNOWLEDGE:
            return self._knowledge_store.query(kind, prefix, limit)
        else:
            return []

    # -------------------------------------------------------------------------
    # 1) Working State 相关的高层封装
    # -------------------------------------------------------------------------
    def set_working_state(self, key: str, data: Dict[str, Any]) -> None:
        """
        写入一条 Working State：
        - key 示例: "conv:{conv_id}:working", "task:{task_id}:context"
        """
        rec = MemoryRecord(
            kind=MemoryKind.WORKING_STATE,
            key=key,
            data=data,
            created_at=datetime.utcnow(),
        )
        self._working_state_store.save(rec)

    def get_working_state(self, key: str) -> Optional[Dict[str, Any]]:
        rec = self._working_state_store.get(MemoryKind.WORKING_STATE, key)
        return rec.data if rec else None

    # -------------------------------------------------------------------------
    # 2) Episodic Memory：Task / Skill 事件
    # -------------------------------------------------------------------------
    def remember_task_run(
        self,
        task_id: str,
        status: str,
        summary: str,
        extra: Dict[str, Any] | None = None,
    ) -> None:
        """
        记录一次 Task 运行事件：
        - key 示例: "task:{task_id}:run:{ts}"
        """
        now = datetime.utcnow()
        data = {
            "task_id": task_id,
            "status": status,   # success / failed / running ...
            "summary": summary,
            "extra": extra or {},
        }
        rec = MemoryRecord(
            kind=MemoryKind.EPISODIC,
            key=f"task:{task_id}:run:{now.isoformat()}",
            data=data,
            created_at=now,
        )
        self._episodic_store.save(rec)
        
        # === 新增：同时保存到向量存储 ===
        if self._vector_store is not None:
            try:
                self._vector_store.save(rec)
            except Exception as vec_err:
                # 向量存储失败不影响主流程
                logger.warning(f"Vector store save failed: {vec_err}")
        # ====================================

    def remember_skill_event(
        self,
        skill_name: str,
        event_type: str,
        status: str,
        detail: str,
        extra: Dict[str, Any] | None = None,
    ) -> None:
        """
        记录一次 Skill 事件（成功/失败/警告等）：
        - key 示例: "skill:{skill_name}:{event_type}:{ts}"
        """
        now = datetime.utcnow()
        data = {
            "skill_name": skill_name,
            "event_type": event_type,  # usage / error / warning ...
            "status": status,
            "detail": detail,
            "extra": extra or {},
        }
        rec = MemoryRecord(
            kind=MemoryKind.EPISODIC,
            key=f"skill:{skill_name}:{event_type}:{now.isoformat()}",
            data=data,
            created_at=now,
        )
        self._episodic_store.save(rec)
        
        # === 新增：同时保存到向量存储 ===
        if self._vector_store is not None:
            try:
                self._vector_store.save(rec)
            except Exception as vec_err:
                # 向量存储失败不影响主流程
                logger.warning(f"Vector store save failed: {vec_err}")
        # ====================================

    def query_task_episodes(
        self,
        task_id: str,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        """
        查询某个 Task 相关的运行事件
        - 按 key 前缀 "task:{task_id}:run" 搜索
        """
        prefix = f"task:{task_id}:run"
        return self._episodic_store.query(
            kind=MemoryKind.EPISODIC,
            prefix=prefix,
            limit=limit,
        )

    def query_skill_episodes(
        self,
        skill_name: str,
        limit: int = 50,
    ) -> List[MemoryRecord]:
        """
        查询某个 Skill 相关的事件
        - 按 key 前缀 "skill:{skill_name}:" 搜索
        """
        prefix = f"skill:{skill_name}:"
        return self._episodic_store.query(
            kind=MemoryKind.EPISODIC,
            prefix=prefix,
            limit=limit,
        )

    # -------------------------------------------------------------------------
    # 3) Knowledge Memory：通用 CRUD 接口（纯存储，不关心业务逻辑）
    # -------------------------------------------------------------------------
    
    # -------------------------------------------------------------------------
    # 4) 通用 Knowledge API：支持任意 key-value 存储
    # -------------------------------------------------------------------------
    def set_knowledge(self, key: str, data: Dict[str, Any]) -> None:
        """
        保存任意知识到 Knowledge Memory
        - key 示例: "skill_stats:excel.append", "user_custom:theme"
        """
        now = datetime.utcnow()
        rec = MemoryRecord(
            kind=MemoryKind.KNOWLEDGE,
            key=key,
            data=data,
            created_at=now,
        )
        self._knowledge_store.save(rec)
    
    def get_knowledge(self, key: str) -> Optional[Dict[str, Any]]:
        """
        获取指定 key 的知识
        """
        rec = self._knowledge_store.get(MemoryKind.KNOWLEDGE, key)
        return rec.data if rec else None
    
    def query_knowledge(self, prefix: str = "", limit: int = 50) -> List[MemoryRecord]:
        """
        查询知识（按 key 前缀）
        """
        return self._knowledge_store.query(
            kind=MemoryKind.KNOWLEDGE,
            prefix=prefix,
            limit=limit,
        )
    
    # -------------------------------------------------------------------------
    # 5) 向量检索 API：语义搜索历史任务
    # -------------------------------------------------------------------------
    def search_similar_tasks(
        self,
        task_description: str,
        status: Optional[str] = None,
        n_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        语义搜索相似的历史任务（用于 RAG 增强 Planner）
        
        Args:
            task_description: 任务描述（用户的新请求）
            status: 过滤状态（"success" 或 "failed"，None 表示不过滤）
            n_results: 返回数量
        
        Returns:
            相似任务列表，每个包含：
            - document: 任务的文本描述
            - metadata: 元数据（状态、时间等）
            - distance: 相似度距离
        """
        if self._vector_store is None:
            return []
        
        try:
            return self._vector_store.get_similar_tasks(
                task_description=task_description,
                status=status,
                n_results=n_results,
            )
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []
    
    # -------------------------------------------------------------------------
    # 6) 遗忘机制：清理旧记忆
    # -------------------------------------------------------------------------
    def cleanup_old_memories(
        self,
        days_to_keep: int = 30,
        keep_successful_tasks: bool = True,
    ) -> Dict[str, int]:
        """
        清理旧的 Episodic Memory（遗忘机制）
        
        策略：
        1. 删除超过 N 天的记录
        2. 可选：保留所有成功的任务（即使很旧）
        3. 失败的任务和技能错误事件会被清理
        
        Args:
            days_to_keep: 保留最近 N 天的记录（默认 30 天）
            keep_successful_tasks: 是否永久保留成功的任务（默认 True）
        
        Returns:
            清理统计: {"episodic_deleted": N, "vector_deleted": M}
        """
        from datetime import timedelta
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        stats = {"episodic_deleted": 0, "vector_deleted": 0}
        
        # 1. 清理 JSONL Episodic Memory
        try:
            episodic_path = self._episodic_store._path
            if episodic_path.exists():
                # 读取所有记录
                with episodic_path.open("r", encoding="utf-8") as f:
                    lines = f.readlines()
                
                # 过滤：保留最近的或成功的任务
                kept_lines = []
                for line in lines:
                    try:
                        item = json.loads(line)
                        created_at = datetime.fromisoformat(item["created_at"])
                        
                        # 如果是最近的记录，保留
                        if created_at >= cutoff_date:
                            kept_lines.append(line)
                            continue
                        
                        # 如果是成功的任务且配置为保留，则保留
                        if keep_successful_tasks and item.get("key", "").startswith("task:"):
                            if item.get("data", {}).get("status") == "success":
                                kept_lines.append(line)
                                continue
                        
                        # 否则删除（计数）
                        stats["episodic_deleted"] += 1
                    except Exception:
                        # 解析失败，保留原行
                        kept_lines.append(line)
                
                # 写回文件
                with episodic_path.open("w", encoding="utf-8") as f:
                    f.writelines(kept_lines)
                
                logger.info(f"Cleaned episodic memory: deleted {stats['episodic_deleted']} old records")
        except Exception as ep_err:
            logger.error(f"Failed to clean episodic memory: {ep_err}")
        
        # 2. 清理 Vector Store（ChromaDB 支持按元数据删除）
        # 注意：ChromaDB 的清理比较复杂，这里简化处理
        # 实际项目中可能需要重建 Collection
        try:
            if self._vector_store:
                # 简化方案：如果向量库太大（> 10000 条），重建
                count = self._vector_store.count()
                if count > 10000:
                    logger.warning(f"Vector store has {count} records, consider rebuilding")
                    # 可以在这里添加重建逻辑
                    # self._vector_store.reset()
                    # ... 重新索引最近的记录
                    # for rec in recent_records:
                    #     self._vector_store.save(rec)
        except Exception as vec_err:
            logger.warning(f"Failed to clean vector store: {vec_err}")
        
        return stats

    # -------------------------------------------------------------------------
    # 7) Session Management (New)
    # -------------------------------------------------------------------------
    def save_session_context(self, session_ctx: Any) -> None:
        """
        保存 SessionContext 到 Working State
        key: "session:{session_id}:context"
        Note: session_ctx must have .session_id and .to_dict()
        """
        key = f"session:{session_ctx.session_id}:context"
        # Use Duck Typing to avoid circular import
        if hasattr(session_ctx, "to_dict"):
            data = session_ctx.to_dict()
        else:
            data = session_ctx # Assume it's already a dict
        
        self.set_working_state(key, data)

    def get_session_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取 SessionContext 数据 (dict)
        """
        key = f"session:{session_id}:context"
        return self.get_working_state(key)
