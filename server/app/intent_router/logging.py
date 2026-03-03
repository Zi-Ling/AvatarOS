# app/router/logging.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol
import time
import uuid

# 如果你有 IntentSpec / RouteType 之类的类型，可以在这里按实际路径导入；
# 为了避免你现在项目结构还未稳定，这里全部用 Any / str 占位。
try:
    # 示例：如果你将来有 IntentSpec 定义在 app.avatar.intent.models 之类
    from app.avatar.intent.models import IntentSpec  # type: ignore
except ImportError:  # 当前阶段先忽略，后面再按真实情况改
    IntentSpec = Any  # type: ignore


# =========================
# 数据结构：日志记录模型
# =========================

@dataclass
class LLMCallLogRecord:
    """
    记录一次 LLM 调用的完整信息（只关心 Router 层看到的内容）。
    注意：这是运行时日志，不是 ORM。
    """
    id: str
    request_id: str

    model: Optional[str] = None
    prompt: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)

    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None

    success: bool = False
    response_text: Optional[str] = None
    error: Optional[str] = None

    usage: Dict[str, Any] = field(default_factory=dict)  # tokens 等信息可选

    def mark_finished(
        self,
        success: bool,
        response_text: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.finished_at = time.time()
        self.success = success
        self.response_text = response_text
        self.error = error
        if usage is not None:
            self.usage = usage

    @property
    def latency_ms(self) -> Optional[float]:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at) * 1000.0


@dataclass
class RouterDecisionLogRecord:
    """
    记录一次路由决策：
    - 输入是什么
    - 解析到的 intent（如果有）
    - 决策类型（走 chat / task / 其它）
    - 最终目标（哪个 avatar / 哪种 handler）
    """
    id: str
    request_id: str

    input_text: str
    created_at: float = field(default_factory=time.time)

    # 这块字段你可以在 Router 内按实际情况填：
    intent_spec: Optional[Dict[str, Any]] = None   # 可存 IntentSpec.to_dict()
    route_type: Optional[str] = None               # e.g. "chat" / "task" / "unknown"
    target: Optional[str] = None                   # e.g. "avatar", "llm_direct"

    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterRequestLog:
    """
    表示一次“对 Router 的请求”（一次用户输入）的完整日志：
    - 一次或多次 LLM 调用
    - 一次最终路由决策
    """
    request_id: str
    created_at: float = field(default_factory=time.time)

    llm_calls: List[LLMCallLogRecord] = field(default_factory=list)
    decision: Optional[RouterDecisionLogRecord] = None

    # 方便后面扩展（例如在这里挂 user_id / session_id）
    meta: Dict[str, Any] = field(default_factory=dict)


# =========================
# 接口：RouterLogger 协议
# =========================

class RouterLogger(Protocol):
    """
    Router + LLM 层使用的日志接口。
    AvatarRouter / LLMClientWrapper 只依赖这个接口，不依赖具体实现。
    """

    # ---- 一个“请求级别”的入口（可选） ----

    def on_request_start(
        self,
        request_id: str,
        input_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        当用户有一条新输入需要经过 Router 处理时调用。
        通常在 AvatarRouter.route(...) 一开始调用。
        """

    # ---- LLM 调用日志 ----

    def on_llm_call_start(
        self,
        request_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        在 Router 层发起一次 LLM 调用时调用。
        返回一个 llm_call_id，用于结束时关联同一条记录。
        """
        ...

    def on_llm_call_end(
        self,
        llm_call_id: str,
        success: bool,
        response_text: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        LLM 调用结束时调用（无论成功/失败）。
        """

    # ---- 路由决策日志 ----

    def on_route_decision(
        self,
        request_id: str,
        route_type: str,
        intent_spec: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Router 最终决定这次请求走哪条路（chat / task / other）时调用。
        """

    # ---- 查询接口 ----

    def get_request_log(self, request_id: str) -> Optional[RouterRequestLog]:
        """获取一次 Router 请求（输入）的完整日志。"""

    def get_all_request_logs(self) -> List[RouterRequestLog]:
        """获取当前 logger 中所有请求日志。"""


# =========================
# 默认实现：内存型 RouterLogger
# =========================

class InMemoryRouterLogger:
    """
    简单的内存实现：
    - 以 request_id 作为 key 存 RouterRequestLog
    - 以 llm_call_id 作为 key 存 LLMCallLogRecord，然后归属到对应 request 下
    """

    def __init__(self) -> None:
        # key: request_id -> RouterRequestLog
        self._requests: Dict[str, RouterRequestLog] = {}
        # key: llm_call_id -> (request_id, LLMCallLogRecord)
        self._llm_calls_index: Dict[str, tuple[str, LLMCallLogRecord]] = {}

    # ---- RouterLogger 接口实现 ----

    def on_request_start(
        self,
        request_id: str,
        input_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        req_log = RouterRequestLog(request_id=request_id)
        req_log.meta["input_text"] = input_text
        if meta:
            req_log.meta.update(meta)
        self._requests[request_id] = req_log

    def on_llm_call_start(
        self,
        request_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        # 确保 request 记录已存在
        if request_id not in self._requests:
            # 如果外层没调用 on_request_start，也可以兜底创建一个
            self._requests[request_id] = RouterRequestLog(request_id=request_id)

        llm_call_id = str(uuid.uuid4())
        record = LLMCallLogRecord(
            id=llm_call_id,
            request_id=request_id,
            model=model,
            prompt=prompt,
            params=params or {},
        )

        self._requests[request_id].llm_calls.append(record)
        self._llm_calls_index[llm_call_id] = (request_id, record)
        return llm_call_id

    def on_llm_call_end(
        self,
        llm_call_id: str,
        success: bool,
        response_text: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        ref = self._llm_calls_index.get(llm_call_id)
        if ref is None:
            # 理论上不应该发生，忽略
            return
        _, record = ref
        record.mark_finished(
            success=success,
            response_text=response_text,
            error=error,
            usage=usage,
        )

    def on_route_decision(
        self,
        request_id: str,
        route_type: str,
        intent_spec: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        req_log = self._requests.get(request_id)
        if req_log is None:
            req_log = RouterRequestLog(request_id=request_id)
            self._requests[request_id] = req_log

        decision = RouterDecisionLogRecord(
            id=str(uuid.uuid4()),
            request_id=request_id,
            input_text=str(req_log.meta.get("input_text", "")),
            route_type=route_type,
            target=target,
            intent_spec=intent_spec,
            meta=meta or {},
        )
        req_log.decision = decision

    def get_request_log(self, request_id: str) -> Optional[RouterRequestLog]:
        return self._requests.get(request_id)

    def get_all_request_logs(self) -> List[RouterRequestLog]:
        return list(self._requests.values())


# =========================
# 空实现：不记录任何东西
# =========================

class NullRouterLogger:
    """
    一个 no-op 实现：啥也不记。
    用于你不想记录日志，但又要传一个 logger 进去的场景。
    """

    def on_request_start(
        self,
        request_id: str,
        input_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        return None

    def on_llm_call_start(
        self,
        request_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        # 仍然返回一个虚假的 id，避免调用方出错
        return str(uuid.uuid4())

    def on_llm_call_end(
        self,
        llm_call_id: str,
        success: bool,
        response_text: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        return None

    def on_route_decision(
        self,
        request_id: str,
        route_type: str,
        intent_spec: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        return None

    def get_request_log(self, request_id: str) -> Optional[RouterRequestLog]:
        return None

    def get_all_request_logs(self) -> List[RouterRequestLog]:
        return []


# =========================
# 数据库实现：DatabaseRouterLogger
# =========================

class DatabaseRouterLogger:
    """
    使用数据库持久化的 RouterLogger 实现。
    记录所有 Router 请求到 router_requests 表，LLM 调用到 llm_calls 表。
    """

    def __init__(self) -> None:
        # 内存索引：request_id -> db_id
        self._request_id_map: Dict[str, str] = {}
        # 内存索引：llm_call_id -> db_id
        self._llm_call_id_map: Dict[str, str] = {}

    def on_request_start(
        self,
        request_id: str,
        input_text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录请求开始"""
        from app.crud.logging import RouterRequestStore
        
        request = RouterRequestStore.create(
            request_id=request_id,
            input_text=input_text,
            meta=meta,
        )
        self._request_id_map[request_id] = request.id

    def on_llm_call_start(
        self,
        request_id: str,
        model: Optional[str],
        prompt: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """记录 LLM 调用开始"""
        from app.crud.logging import LLMCallStore
        
        llm_call_id = str(uuid.uuid4())
        
        # 创建 LLM 调用记录
        llm_call = LLMCallStore.create(
            call_id=llm_call_id,
            source="router",
            parent_id=request_id,
            model=model,
            prompt=prompt,
            params=params,
        )
        
        self._llm_call_id_map[llm_call_id] = llm_call.id
        return llm_call_id

    def on_llm_call_end(
        self,
        llm_call_id: str,
        success: bool,
        response_text: Optional[str] = None,
        error: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录 LLM 调用结束"""
        from app.crud.logging import LLMCallStore
        
        db_id = self._llm_call_id_map.get(llm_call_id)
        if not db_id:
            return
        
        LLMCallStore.update_result(
            db_id,
            success=success,
            response=response_text,
            error=error,
            usage=usage,
        )

    def on_route_decision(
        self,
        request_id: str,
        route_type: str,
        intent_spec: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录路由决策"""
        from app.crud.logging import RouterRequestStore
        
        # 提取 task_id（如果有）
        task_id = None
        if meta and "task_id" in meta:
            task_id = meta["task_id"]
        
        RouterRequestStore.update_decision(
            request_id=request_id,
            route_type=route_type,
            target=target,
            intent_spec=intent_spec,
            task_id=task_id,
        )

    def get_request_log(self, request_id: str) -> Optional[RouterRequestLog]:
        """获取一次 Router 请求的完整日志"""
        from app.crud.logging import RouterRequestStore, LLMCallStore
        
        # 获取请求记录
        request = RouterRequestStore.get(request_id)
        if not request:
            return None
        
        # 获取关联的 LLM 调用
        llm_calls_db = LLMCallStore.list_by_parent(request_id)
        
        # 转换为日志记录
        llm_calls = []
        for llm_call in llm_calls_db:
            llm_calls.append(
                LLMCallLogRecord(
                    id=llm_call.id,
                    request_id=request_id,
                    model=llm_call.model,
                    prompt=llm_call.prompt,
                    params=llm_call.params or {},
                    started_at=llm_call.started_at.timestamp(),
                    finished_at=llm_call.finished_at.timestamp() if llm_call.finished_at else None,
                    success=llm_call.success,
                    response_text=llm_call.response,
                    error=llm_call.error,
                    usage=llm_call.usage or {},
                )
            )
        
        # 构造决策记录
        decision = None
        if request.route_type:
            decision = RouterDecisionLogRecord(
                id=str(uuid.uuid4()),
                request_id=request_id,
                input_text=request.input_text,
                created_at=request.created_at.timestamp(),
                intent_spec=request.intent_spec,
                route_type=request.route_type,
                target=request.target,
                meta=request.meta or {},
            )
        
        return RouterRequestLog(
            request_id=request_id,
            created_at=request.created_at.timestamp(),
            llm_calls=llm_calls,
            decision=decision,
            meta=request.meta or {},
        )

    def get_all_request_logs(self) -> List[RouterRequestLog]:
        """获取当前 logger 中所有请求日志（限制数量）"""
        from app.crud.logging import RouterRequestStore
        
        requests = RouterRequestStore.list_all(limit=100)
        
        logs = []
        for request in requests:
            log = self.get_request_log(request.request_id)
            if log:
                logs.append(log)
        
        return logs


# =========================
# 工厂函数（可选）
# =========================

def create_default_router_logger() -> RouterLogger:
    """
    Router 默认使用的 logger。
    以后如果你想换成文件/DB/外部监控实现，只要改这里即可。
    """
    return DatabaseRouterLogger()
