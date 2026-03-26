"""SubtaskGraph persistence — save/load snapshots for gate resume and crash recovery.

All tunable parameters are in SubtaskGraphPersistenceConfig.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubtaskGraphPersistenceConfig:
    """Tunable parameters for SubtaskGraph persistence."""
    # Max chars of env_context to persist (prevents DB bloat)
    env_context_max_chars: int = 50_000
    # Max chars of results JSON to persist
    results_max_chars: int = 100_000
    # Keys from env_context to persist for resume (others are rebuilt)
    env_context_persist_keys: tuple = (
        "session_id", "run_id", "task_id", "workspace_path",
        "session_workspace_path", "gate_answers", "resumed_from_gate",
        "force_multi_agent", "_execution_depth",
    )
    # Retention: max snapshots to keep per task_session_id
    max_snapshots_per_session: int = 3


def save_subtask_graph(
    task_session_id: str,
    graph: Any,  # SubtaskGraph
    results: Dict[str, Dict[str, Any]],
    intent: str,
    env_context: Dict[str, Any],
    reason: str = "gate_waiting",
    config: Optional[SubtaskGraphPersistenceConfig] = None,
) -> Optional[str]:
    """Persist a SubtaskGraph snapshot to DB.

    Returns snapshot ID on success, None on failure.
    """
    cfg = config or SubtaskGraphPersistenceConfig()
    try:
        from app.db.long_task_models import SubtaskGraphSnapshot
        from app.db.database import get_session

        graph_json = json.dumps(graph.to_dict(), ensure_ascii=False)

        # Truncate results if too large
        results_json = json.dumps(results, ensure_ascii=False)
        if len(results_json) > cfg.results_max_chars:
            results_json = results_json[:cfg.results_max_chars]

        # Persist only essential env_context keys
        env_subset = {
            k: v for k, v in env_context.items()
            if k in cfg.env_context_persist_keys
        }
        env_json = json.dumps(env_subset, ensure_ascii=False)
        if len(env_json) > cfg.env_context_max_chars:
            env_json = env_json[:cfg.env_context_max_chars]

        record = SubtaskGraphSnapshot(
            task_session_id=task_session_id,
            graph_id=graph.graph_id,
            graph_json=graph_json,
            results_json=results_json,
            snapshot_reason=reason,
            exec_mode="multi_agent",
            intent=intent,
            env_context_json=env_json,
        )
        with get_session() as db:
            db.add(record)
            db.commit()
            snapshot_id = record.id

        # Cleanup: keep only the most recent N snapshots per session
        try:
            _cleanup_old_snapshots(task_session_id, cfg.max_snapshots_per_session)
        except Exception as _clean_err:
            logger.debug("[GraphPersistence] Cleanup failed: %s", _clean_err)

        logger.info(
            "[GraphPersistence] Saved snapshot %s for session %s (reason=%s, nodes=%d)",
            snapshot_id, task_session_id, reason, len(graph.nodes),
        )
        return snapshot_id

    except Exception as exc:
        logger.warning("[GraphPersistence] Save failed: %s", exc)
        return None


def load_subtask_graph(
    task_session_id: str,
) -> Optional[Dict[str, Any]]:
    """Load the latest SubtaskGraph snapshot for a task session.

    Returns dict with keys: graph, results, intent, env_context, snapshot_id
    or None if no snapshot found.
    """
    try:
        from app.db.long_task_models import SubtaskGraphSnapshot
        from app.db.database import get_session
        from app.avatar.runtime.multiagent.core.subtask_graph import SubtaskGraph

        with get_session() as db:
            from sqlmodel import select
            stmt = (
                select(SubtaskGraphSnapshot)
                .where(SubtaskGraphSnapshot.task_session_id == task_session_id)
                .order_by(SubtaskGraphSnapshot.created_at.desc())
                .limit(1)
            )
            record = db.exec(stmt).first()
            if record is None:
                return None

            graph_data = json.loads(record.graph_json)
            results = json.loads(record.results_json or "{}")
            env_context = json.loads(record.env_context_json or "{}")
            intent = record.intent
            snapshot_id = record.id

        graph = SubtaskGraph.from_dict(graph_data)

        logger.info(
            "[GraphPersistence] Loaded snapshot %s for session %s (nodes=%d)",
            snapshot_id, task_session_id, len(graph.nodes),
        )
        return {
            "graph": graph,
            "results": results,
            "intent": intent,
            "env_context": env_context,
            "snapshot_id": snapshot_id,
        }

    except Exception as exc:
        logger.warning("[GraphPersistence] Load failed: %s", exc)
        return None


def _cleanup_old_snapshots(task_session_id: str, keep: int) -> int:
    """Delete old snapshots, keeping only the most recent `keep` per session.

    Returns number of deleted snapshots.
    """
    from app.db.long_task_models import SubtaskGraphSnapshot
    from app.db.database import get_session

    with get_session() as db:
        from sqlmodel import select
        stmt = (
            select(SubtaskGraphSnapshot)
            .where(SubtaskGraphSnapshot.task_session_id == task_session_id)
            .order_by(SubtaskGraphSnapshot.created_at.desc())
        )
        all_snaps = list(db.exec(stmt).all())
        if len(all_snaps) <= keep:
            return 0

        to_delete = all_snaps[keep:]
        for snap in to_delete:
            db.delete(snap)
        db.commit()

        logger.debug(
            "[GraphPersistence] Cleaned up %d old snapshots for %s",
            len(to_delete), task_session_id,
        )
        return len(to_delete)
