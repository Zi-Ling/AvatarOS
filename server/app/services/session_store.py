# server/app/services/session_store.py
"""
ExecutionSessionStore — ExecutionSession 生命周期管理

状态机转换：非法转换抛 InvalidTransitionError，调用方必须显式处理。
并发防护：transition 使用条件更新（WHERE status=current），更新 0 行说明竞态发生。
PlannerInvocation：独立表，append-only，session 表只保留聚合统计。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlmodel import Session, select, text

from app.db.database import engine
from app.db.system import ExecutionSession, PlannerInvocation

logger = logging.getLogger(__name__)

# 合法状态转换表
_VALID_TRANSITIONS: Dict[str, list] = {
    "created":   ["planned", "running", "completed", "failed", "cancelled"],
    "planned":   ["running", "failed", "cancelled"],
    "running":   ["waiting", "completed", "failed", "cancelled"],
    "waiting":   ["running", "failed", "cancelled"],
    "completed": ["archived"],
    "failed":    ["archived"],
    "cancelled": ["archived"],
    "archived":  [],
}

_SUMMARY_MAX = 500


def _summarize(obj: Any) -> str:
    s = json.dumps(obj, default=str, ensure_ascii=False)
    return s if len(s) <= _SUMMARY_MAX else s[:_SUMMARY_MAX] + "..."


class InvalidTransitionError(Exception):
    """非法状态机转换"""
    pass


class ExecutionSessionStore:
    """ExecutionSession CRUD + 状态机"""

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    @staticmethod
    def create(
        goal: str,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        request_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        policy_snapshot: Optional[Dict[str, Any]] = None,
        runtime_config_snapshot: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSession:
        session_obj = ExecutionSession(
            goal=goal,
            run_id=run_id,
            task_id=task_id,
            request_id=request_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            workspace_path=workspace_path,
            policy_snapshot=policy_snapshot,
            runtime_config_snapshot=runtime_config_snapshot,
            status="created",
        )
        with Session(engine) as db:
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)
        logger.info(f"[SessionStore] Created session {session_obj.id} run={run_id}")
        return session_obj

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    def get(session_id: str) -> Optional[ExecutionSession]:
        with Session(engine) as db:
            return db.get(ExecutionSession, session_id)

    @staticmethod
    def get_by_run_id(run_id: str) -> Optional[ExecutionSession]:
        with Session(engine) as db:
            return db.exec(
                select(ExecutionSession).where(ExecutionSession.run_id == run_id)
            ).first()

    # ------------------------------------------------------------------
    # 状态转换（带条件更新防竞态）
    # ------------------------------------------------------------------

    @staticmethod
    def transition(session_id: str, new_status: str, **kwargs) -> None:
        """
        状态机转换。

        - 非法转换：抛 InvalidTransitionError
        - 竞态（条件更新 0 行）：抛 InvalidTransitionError
        - kwargs 可携带额外字段更新（error_message、result_status 等）
        """
        with Session(engine) as db:
            obj = db.get(ExecutionSession, session_id)
            if not obj:
                raise InvalidTransitionError(
                    f"Session {session_id} not found"
                )

            current = obj.status
            allowed = _VALID_TRANSITIONS.get(current, [])
            if new_status not in allowed:
                # 写 invalid_transition trace event
                try:
                    from app.avatar.runtime.graph.storage.step_trace_store import get_step_trace_store
                    get_step_trace_store().record_session_event(
                        session_id=session_id,
                        event_type="invalid_transition",
                        payload={"from": current, "to": new_status, "reason": "not in allowed transitions"},
                    )
                except Exception:
                    pass
                raise InvalidTransitionError(
                    f"Invalid transition {current} -> {new_status} for session {session_id}"
                )

            now = datetime.now(timezone.utc)

            # 条件更新：WHERE id=? AND status=current，防止并发覆盖
            result = db.exec(
                text(
                    "UPDATE execution_sessions SET status=:new_status WHERE id=:sid AND status=:cur_status"
                ).bindparams(new_status=new_status, sid=session_id, cur_status=current)
            )
            if result.rowcount == 0:
                raise InvalidTransitionError(
                    f"Concurrent transition detected for session {session_id}: "
                    f"expected status={current}, already changed"
                )

            # 更新时间戳和附加字段
            obj = db.get(ExecutionSession, session_id)
            if new_status == "planned":
                obj.planned_at = now
            elif new_status == "running":
                if obj.started_at is None:
                    obj.started_at = now
            elif new_status in ("completed", "failed", "cancelled"):
                obj.completed_at = now
            elif new_status == "archived":
                obj.archived_at = now

            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)

            db.add(obj)
            db.commit()

        logger.info(f"[SessionStore] Session {session_id}: {current} -> {new_status}")

    # ------------------------------------------------------------------
    # PlannerInvocation 写入（独立表，append-only）
    # ------------------------------------------------------------------

    @staticmethod
    def record_planner_invocation(
        session_id: str,
        invocation_index: int,
        planner_input: Any,
        planner_output: Any,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        latency_ms: Optional[int] = None,
    ) -> None:
        """
        写入一条 PlannerInvocation 记录，同时原子增量更新 session 聚合统计。
        """
        full_input = json.dumps(planner_input, default=str, ensure_ascii=False)
        full_output = json.dumps(planner_output, default=str, ensure_ascii=False)

        invocation = PlannerInvocation(
            session_id=session_id,
            invocation_index=invocation_index,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            input_summary=_summarize(planner_input),
            output_summary=_summarize(planner_output),
            full_input_json=full_input,
            full_output_json=full_output,
        )

        with Session(engine) as db:
            db.add(invocation)
            # 原子增量更新 session 聚合统计
            db.exec(
                text(
                    "UPDATE execution_sessions SET "
                    "planner_invocations = planner_invocations + 1, "
                    "planner_tokens = planner_tokens + :tokens, "
                    "planner_cost_usd = planner_cost_usd + :cost "
                    "WHERE id = :sid"
                ).bindparams(tokens=tokens_used, cost=cost_usd, sid=session_id)
            )
            db.commit()

    # ------------------------------------------------------------------
    # 节点统计（原子增量 + 最终 reconcile）
    # ------------------------------------------------------------------

    @staticmethod
    def increment_node_stat(session_id: str, field: str) -> None:
        """
        原子增量更新单个节点统计字段（completed_nodes / failed_nodes）。
        在每个节点完成/失败时调用，保证中途中断也有准确进度。
        """
        if field not in ("completed_nodes", "failed_nodes", "total_nodes"):
            raise ValueError(f"Unknown stat field: {field}")
        with Session(engine) as db:
            db.exec(
                text(
                    f"UPDATE execution_sessions SET {field} = {field} + 1 WHERE id = :sid"
                ).bindparams(sid=session_id)
            )
            db.commit()

    @staticmethod
    def reconcile_node_stats(
        session_id: str,
        total_nodes: int,
        completed_nodes: int,
        failed_nodes: int,
    ) -> None:
        """执行结束时做一次最终 reconcile，确保统计准确。"""
        with Session(engine) as db:
            obj = db.get(ExecutionSession, session_id)
            if not obj:
                return
            obj.total_nodes = total_nodes
            obj.completed_nodes = completed_nodes
            obj.failed_nodes = failed_nodes
            db.add(obj)
            db.commit()

    # ------------------------------------------------------------------
    # 启动清理：标记孤立的 running/waiting/created/planned session 为 failed
    # ------------------------------------------------------------------

    @staticmethod
    def cleanup_zombie_sessions(max_age_hours: int = 2) -> int:
        """
        服务启动时调用。将超过 max_age_hours 仍处于非终态的 session
        标记为 failed（进程崩溃/重启导致的孤立 session）。

        Returns: 清理的 session 数量。
        """
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        non_terminal = ("created", "planned", "running", "waiting")
        cleaned = 0

        with Session(engine) as db:
            stale = db.exec(
                select(ExecutionSession).where(
                    ExecutionSession.status.in_(non_terminal),
                    ExecutionSession.created_at < cutoff,
                )
            ).all()

            now = datetime.now(timezone.utc)
            for obj in stale:
                obj.status = "failed"
                obj.result_status = "interrupted"
                obj.error_message = "Session interrupted: process restarted or crashed"
                obj.completed_at = now
                db.add(obj)
                cleaned += 1

            if cleaned > 0:
                db.commit()
                logger.info(f"[SessionStore] Cleaned up {cleaned} zombie session(s) older than {max_age_hours}h")

        return cleaned
