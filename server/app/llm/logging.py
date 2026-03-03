# app/llm/logging.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol
import time
import uuid


# =========================
# 数据结构：LLM 调用日志
# =========================

@dataclass
class LLMCallLogRecord:
    """
    记录一次 LLM 调用的完整信息：
    - prompt
    - model
    - 参数
    - 返回值
    - 用时
    """

    id: str
    call_id: str   # 和 llm_client 本身的 request_id, 或 router 的 request_id 区分开

    model: Optional[str] = None
    prompt: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)

    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    success: bool = False
    response: Any = None
    error: Optional[str] = None
    usage: Dict[str, Any] = field(default_factory=dict)

    def mark_finished(
        self,
        success: bool,
        response: Any = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.finished_at = time.time()
        self.success = success
        self.response = response
        self.error = error
        if usage is not None:
            self.usage = usage

    @property
    def latency_ms(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at) * 1000.0


# =========================
# LLM Logger 接口
# =========================

class LLMLogger(Protocol):
    """
    给 LLMClient 使用的日志抽象接口：
    - LLM client 开始调用时调用 on_llm_start
    - LLM client 结束调用时调用 on_llm_end
    """

    def on_llm_start(
        self,
        call_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> str:
        """
        返回 llm_log_id（用来关联 llm_end）
        """

    def on_llm_end(
        self,
        llm_log_id: str,
        success: bool,
        response: Any = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        结束一次 LLM 调用
        """

    def get_log(self, llm_log_id: str) -> Optional[LLMCallLogRecord]:
        """获取单条日志"""

    def get_all_logs(self) -> List[LLMCallLogRecord]:
        """返回全部 LLM 调用日志"""


# =========================
# 默认实现：InMemoryLLMLogger
# =========================

class InMemoryLLMLogger:
    def __init__(self) -> None:
        # key: llm_log_id -> LLMCallLogRecord
        self._records: Dict[str, LLMCallLogRecord] = {}

    def on_llm_start(
        self,
        call_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> str:
        llm_log_id = str(uuid.uuid4())
        record = LLMCallLogRecord(
            id=llm_log_id,
            call_id=call_id,
            model=model,
            prompt=prompt,
            params=params or {},
        )
        self._records[llm_log_id] = record
        return llm_log_id

    def on_llm_end(
        self,
        llm_log_id: str,
        success: bool,
        response: Any = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._records.get(llm_log_id)
        if not record:
            return
        record.mark_finished(
            success=success,
            response=response,
            error=error,
            usage=usage,
        )

    def get_log(self, llm_log_id: str) -> Optional[LLMCallLogRecord]:
        return self._records.get(llm_log_id)

    def get_all_logs(self) -> List[LLMCallLogRecord]:
        return list(self._records.values())


# =========================
# 空实现
# =========================

class NullLLMLogger:
    def on_llm_start(
        self,
        call_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> str:
        return str(uuid.uuid4())

    def on_llm_end(
        self,
        llm_log_id: str,
        success: bool,
        response: Any = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        return None

    def get_log(self, llm_log_id: str) -> Optional[LLMCallLogRecord]:
        return None

    def get_all_logs(self) -> List[LLMCallLogRecord]:
        return []


# =========================
# 数据库实现：DatabaseLLMLogger
# =========================

class DatabaseLLMLogger:
    """
    使用数据库持久化的 LLMLogger 实现。
    记录所有 LLM 调用到 llm_calls 表。
    """

    def __init__(self, source: str = "unknown") -> None:
        """
        初始化 DatabaseLLMLogger
        
        Args:
            source: LLM 调用来源标识（router/planner/skill/other）
        """
        self._source = source
        # 内存索引：llm_log_id -> db_id
        self._id_map: Dict[str, str] = {}

    def on_llm_start(
        self,
        call_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]],
    ) -> str:
        """
        记录 LLM 调用开始
        
        返回 llm_log_id（用来关联 llm_end）
        """
        from app.crud.logging import LLMCallStore
        
        llm_log_id = str(uuid.uuid4())
        
        # 创建数据库记录
        record = LLMCallStore.create(
            call_id=call_id,
            source=self._source,
            parent_id=call_id,  # 使用 call_id 作为 parent_id（可以关联到 router request 等）
            model=model,
            prompt=prompt,
            params=params or {},
        )
        
        # 保存映射关系
        self._id_map[llm_log_id] = record.id
        
        return llm_log_id

    def on_llm_end(
        self,
        llm_log_id: str,
        success: bool,
        response: Any = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录 LLM 调用结束
        """
        from app.crud.logging import LLMCallStore
        
        db_id = self._id_map.get(llm_log_id)
        if not db_id:
            return
        
        # 提取响应文本
        response_text = None
        if response is not None:
            if isinstance(response, str):
                response_text = response
            elif isinstance(response, dict):
                response_text = response.get("text") or str(response)
            else:
                response_text = str(response)
        
        # 更新数据库记录
        LLMCallStore.update_result(
            db_id,
            success=success,
            response=response_text,
            error=error,
            usage=usage,
        )

    def get_log(self, llm_log_id: str) -> Optional[LLMCallLogRecord]:
        """获取单条日志"""
        from app.crud.logging import LLMCallStore
        
        db_id = self._id_map.get(llm_log_id)
        if not db_id:
            return None
        
        record = LLMCallStore.get(db_id)
        if not record:
            return None
        
        # 转换为 LLMCallLogRecord
        return LLMCallLogRecord(
            id=record.id,
            call_id=record.call_id,
            model=record.model,
            prompt=record.prompt,
            params=record.params or {},
            started_at=record.started_at.timestamp(),
            finished_at=record.finished_at.timestamp() if record.finished_at else None,
            success=record.success,
            response=record.response,
            error=record.error,
            usage=record.usage or {},
        )

    def get_all_logs(self) -> List[LLMCallLogRecord]:
        """返回全部 LLM 调用日志（限制数量）"""
        from app.crud.logging import LLMCallStore
        
        records = LLMCallStore.list_by_source(self._source, limit=100)
        
        logs = []
        for record in records:
            logs.append(
                LLMCallLogRecord(
                    id=record.id,
                    call_id=record.call_id,
                    model=record.model,
                    prompt=record.prompt,
                    params=record.params or {},
                    started_at=record.started_at.timestamp(),
                    finished_at=record.finished_at.timestamp() if record.finished_at else None,
                    success=record.success,
                    response=record.response,
                    error=record.error,
                    usage=record.usage or {},
                )
            )
        
        return logs


# =========================
# 工厂函数
# =========================

def create_default_llm_logger(source: str = "unknown") -> LLMLogger:
    """
    创建默认的 LLM Logger（数据库版本）
    
    Args:
        source: LLM 调用来源标识
    """
    return DatabaseLLMLogger(source=source)
