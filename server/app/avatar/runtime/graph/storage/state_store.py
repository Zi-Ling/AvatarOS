"""
StateStore - Graph Execution State Persistence

Persists ExecutionGraph and ExecutionContext state to SQLite for:
- Crash recovery and resumption
- Audit trail
- Version history

Requirements: 12.1-12.7, 29.11, 33.6
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from sqlmodel import SQLModel, Field, Session, select, create_engine, Column, JSON as SQLJSON
from sqlalchemy import Text

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

# Default checkpoint interval (every N nodes completed)
DEFAULT_CHECKPOINT_INTERVAL = 5


# ==========================================
# Database Models
# ==========================================

class ExecutionGraphRecord(SQLModel, table=True):
    """Persisted ExecutionGraph record. Requirements: 12.1"""
    __tablename__ = "graph_execution_graphs"

    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: str = Field(index=True, description="ExecutionGraph.id")
    goal: str
    status: str
    graph_json: str = Field(sa_column=Column(Text), description="Full serialized graph JSON")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GraphSnapshotRecord(SQLModel, table=True):
    """Point-in-time snapshot of graph + context. Requirements: 12.2, 12.3"""
    __tablename__ = "graph_snapshots"

    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: str = Field(index=True)
    snapshot_version: int = Field(description="Monotonically increasing snapshot number")
    graph_json: str = Field(sa_column=Column(Text))
    context_json: str = Field(sa_column=Column(Text), description="Serialized ExecutionContext")
    is_terminal: bool = Field(default=False, description="True if graph reached terminal state")
    nodes_completed: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NodeExecutionLogRecord(SQLModel, table=True):
    """Per-node execution log. Requirements: 12.1"""
    __tablename__ = "graph_node_execution_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    graph_id: str = Field(index=True)
    node_id: str = Field(index=True)
    capability_name: str
    status: str
    inputs_json: str = Field(sa_column=Column(Text), default="{}")
    outputs_json: str = Field(sa_column=Column(Text), default="{}")
    error_message: Optional[str] = None
    retry_count: int = Field(default=0)
    execution_cost: float = Field(default=0.0)
    execution_latency: float = Field(default=0.0)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ==========================================
# StateStore
# ==========================================

class StateStore:
    """
    Persists and restores ExecutionGraph state.

    Features:
    - Checkpoint at configurable intervals (default: every 5 nodes)
    - Always snapshot on terminal states (SUCCESS/FAILED)
    - Load latest snapshot for resumption
    - Rollback to previous snapshot
    - Replay execution from snapshot

    Requirements: 12.1-12.7, 29.11, 33.6
    """

    def __init__(
        self,
        engine=None,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL
    ):
        """
        Args:
            engine: SQLAlchemy engine (uses default app engine if None)
            checkpoint_interval: Snapshot every N completed nodes (Requirement 12.2)
        """
        if engine is None:
            from app.db.database import engine as default_engine
            engine = default_engine

        self._engine = engine
        self.checkpoint_interval = checkpoint_interval

        # Ensure tables exist
        SQLModel.metadata.create_all(self._engine, tables=[
            ExecutionGraphRecord.__table__,
            GraphSnapshotRecord.__table__,
            NodeExecutionLogRecord.__table__,
        ])

        logger.info(
            f"[StateStore] Initialized with checkpoint_interval={checkpoint_interval}"
        )

    def save_graph(self, graph: 'ExecutionGraph') -> None:
        """
        Persist or update the graph record.

        Requirements: 12.1
        """
        graph_json = graph.to_json()

        with Session(self._engine) as session:
            existing = session.exec(
                select(ExecutionGraphRecord).where(
                    ExecutionGraphRecord.graph_id == graph.id
                )
            ).first()

            if existing:
                existing.status = graph.status.value
                existing.graph_json = graph_json
                existing.updated_at = datetime.now(UTC)
                session.add(existing)
            else:
                record = ExecutionGraphRecord(
                    graph_id=graph.id,
                    goal=graph.goal,
                    status=graph.status.value,
                    graph_json=graph_json,
                )
                session.add(record)

            session.commit()

    def checkpoint(
        self,
        graph: 'ExecutionGraph',
        context: Optional['ExecutionContext'] = None,
        force: bool = False
    ) -> bool:
        """
        Create a snapshot if checkpoint interval is reached or forced.

        Args:
            graph: Current graph state
            context: Current execution context
            force: Force snapshot regardless of interval

        Returns:
            True if snapshot was created

        Requirements: 12.2, 12.3, 12.4
        """
        # Count completed nodes
        from app.avatar.runtime.graph.models.step_node import NodeStatus
        completed = sum(
            1 for n in graph.nodes.values()
            if n.status in (NodeStatus.SUCCESS, NodeStatus.FAILED, NodeStatus.SKIPPED)
        )

        # Check if terminal
        is_terminal = graph.status.value in ("success", "failed", "cancelled")

        # Decide whether to snapshot
        should_snapshot = force or is_terminal

        if not should_snapshot and self.checkpoint_interval > 0:
            # Snapshot every N completed nodes
            last_snapshot = self._get_snapshot_count(graph.id)
            should_snapshot = (completed > 0 and completed % self.checkpoint_interval == 0
                               and completed > last_snapshot * self.checkpoint_interval)

        if not should_snapshot:
            return False

        self._create_snapshot(graph, context, is_terminal, completed)
        return True

    def _create_snapshot(
        self,
        graph: 'ExecutionGraph',
        context: Optional['ExecutionContext'],
        is_terminal: bool,
        nodes_completed: int
    ) -> GraphSnapshotRecord:
        """Create a snapshot record."""
        graph_json = graph.to_json()
        context_json = self._serialize_context(context)

        with Session(self._engine) as session:
            version = self._get_snapshot_count(graph.id)

            record = GraphSnapshotRecord(
                graph_id=graph.id,
                snapshot_version=version,
                graph_json=graph_json,
                context_json=context_json,
                is_terminal=is_terminal,
                nodes_completed=nodes_completed,
            )
            session.add(record)
            session.commit()
            session.refresh(record)

        logger.info(
            f"[StateStore] Snapshot v{version} for graph {graph.id} "
            f"(terminal={is_terminal}, nodes_completed={nodes_completed})"
        )
        return record

    def load_latest(self, graph_id: str) -> Optional[Dict[str, Any]]:
        """
        Load the most recent snapshot for a graph.

        Returns:
            Dict with 'graph_json' and 'context_json', or None if not found

        Requirements: 12.6
        """
        with Session(self._engine) as session:
            record = session.exec(
                select(GraphSnapshotRecord)
                .where(GraphSnapshotRecord.graph_id == graph_id)
                .order_by(GraphSnapshotRecord.snapshot_version.desc())
            ).first()

            if record is None:
                return None

            return {
                "graph_json": record.graph_json,
                "context_json": record.context_json,
                "snapshot_version": record.snapshot_version,
                "is_terminal": record.is_terminal,
                "nodes_completed": record.nodes_completed,
            }

    def load_snapshot(self, graph_id: str, version: int) -> Optional[Dict[str, Any]]:
        """
        Load a specific snapshot version.

        Requirements: 12.6
        """
        with Session(self._engine) as session:
            record = session.exec(
                select(GraphSnapshotRecord)
                .where(
                    GraphSnapshotRecord.graph_id == graph_id,
                    GraphSnapshotRecord.snapshot_version == version
                )
            ).first()

            if record is None:
                return None

            return {
                "graph_json": record.graph_json,
                "context_json": record.context_json,
                "snapshot_version": record.snapshot_version,
                "is_terminal": record.is_terminal,
            }

    def rollback(self, graph_id: str, to_version: int) -> Optional[Dict[str, Any]]:
        """
        Rollback to a previous snapshot version.

        Deletes all snapshots after to_version and returns the target snapshot.

        Requirements: 12.7
        """
        with Session(self._engine) as session:
            # Delete snapshots after target version
            records_to_delete = session.exec(
                select(GraphSnapshotRecord)
                .where(
                    GraphSnapshotRecord.graph_id == graph_id,
                    GraphSnapshotRecord.snapshot_version > to_version
                )
            ).all()

            for record in records_to_delete:
                session.delete(record)
            session.commit()

        logger.info(
            f"[StateStore] Rolled back graph {graph_id} to version {to_version}, "
            f"deleted {len(records_to_delete)} snapshots"
        )

        return self.load_snapshot(graph_id, to_version)

    def log_node_execution(
        self,
        graph_id: str,
        node_id: str,
        capability_name: str,
        status: str,
        inputs: Optional[Dict[str, Any]] = None,
        outputs: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
        execution_cost: float = 0.0,
        execution_latency: float = 0.0,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ) -> None:
        """Log a node execution event. Requirements: 12.1"""
        with Session(self._engine) as session:
            record = NodeExecutionLogRecord(
                graph_id=graph_id,
                node_id=node_id,
                capability_name=capability_name,
                status=status,
                inputs_json=json.dumps(inputs or {}, default=str),
                outputs_json=json.dumps(outputs or {}, default=str),
                error_message=error_message,
                retry_count=retry_count,
                execution_cost=execution_cost,
                execution_latency=execution_latency,
                started_at=started_at,
                completed_at=completed_at,
            )
            session.add(record)
            session.commit()

    def get_node_logs(self, graph_id: str) -> List[Dict[str, Any]]:
        """Get all node execution logs for a graph."""
        with Session(self._engine) as session:
            records = session.exec(
                select(NodeExecutionLogRecord)
                .where(NodeExecutionLogRecord.graph_id == graph_id)
                .order_by(NodeExecutionLogRecord.id)
            ).all()

            return [
                {
                    "node_id": r.node_id,
                    "capability_name": r.capability_name,
                    "status": r.status,
                    "retry_count": r.retry_count,
                    "execution_cost": r.execution_cost,
                    "execution_latency": r.execution_latency,
                    "error_message": r.error_message,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in records
            ]

    def _get_snapshot_count(self, graph_id: str) -> int:
        """Get number of existing snapshots for a graph."""
        with Session(self._engine) as session:
            records = session.exec(
                select(GraphSnapshotRecord)
                .where(GraphSnapshotRecord.graph_id == graph_id)
            ).all()
            return len(records)

    def _serialize_context(self, context: Optional['ExecutionContext']) -> str:
        """Serialize ExecutionContext to JSON string."""
        if context is None:
            return "{}"
        try:
            return json.dumps({
                "graph_id": context.graph_id,
                "node_outputs": context.node_outputs,
                "variables": context.variables,
                "session_memory": context.session_memory,
            }, default=str)
        except Exception as e:
            logger.warning(f"[StateStore] Failed to serialize context: {e}")
            return "{}"
