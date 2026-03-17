# server/app/avatar/runtime/graph/artifact_dep_graph.py
"""
ArtifactDependencyGraph — 产物依赖图与 Stale 传播

维护产物之间的有向依赖关系（DAG），支持两级 stale 传播：
- hard_stale: 上游 content_hash 变化 → 所有直接和间接下游标记 hard_stale
- soft_stale: 上游版本递增但 content_hash 未变 → 下游标记 soft_stale（不升级为 hard_stale）

传播幂等且可重入：同一上游改动多次触发不会导致重复或不一致的下游状态。
"""
from __future__ import annotations

import logging
from collections import deque

from app.services.artifact_store import ArtifactStore

logger = logging.getLogger(__name__)

# Stale 类型常量
HARD_STALE = "hard_stale"
SOFT_STALE = "soft_stale"


class ArtifactDependencyGraph:
    """
    产物依赖图（内存结构 + ArtifactStore 持久化）。

    内部使用 dict-based 邻接表：
    - _downstream: artifact_id → set of downstream artifact_ids
    - _upstream:   artifact_id → set of upstream artifact_ids
    - _artifacts:  artifact_id → task_session_id 映射
    """

    def __init__(self, event_stream=None) -> None:
        # 邻接表
        self._downstream: dict[str, set[str]] = {}
        self._upstream: dict[str, set[str]] = {}
        # artifact_id → task_session_id
        self._artifacts: dict[str, str] = {}
        self._event_stream = event_stream

    # ------------------------------------------------------------------
    # 注册产物
    # ------------------------------------------------------------------

    def register_artifact(self, artifact_id: str, task_session_id: str) -> None:
        """在依赖图中注册一个产物节点。"""
        if artifact_id in self._artifacts:
            logger.debug(
                f"[ArtifactDepGraph] Artifact {artifact_id} already registered, skipping"
            )
            return
        self._artifacts[artifact_id] = task_session_id
        self._downstream.setdefault(artifact_id, set())
        self._upstream.setdefault(artifact_id, set())
        logger.info(
            f"[ArtifactDepGraph] Registered artifact {artifact_id} "
            f"for task_session {task_session_id}"
        )

    # ------------------------------------------------------------------
    # 添加依赖边
    # ------------------------------------------------------------------

    def add_dependency(self, upstream_id: str, downstream_id: str) -> None:
        """
        添加一条依赖边：downstream 依赖 upstream。

        两个 artifact 都必须已注册，否则抛出 ValueError。
        重复添加同一条边为幂等操作（no-op）。
        """
        if upstream_id not in self._artifacts:
            raise ValueError(
                f"Upstream artifact {upstream_id} not registered in dependency graph"
            )
        if downstream_id not in self._artifacts:
            raise ValueError(
                f"Downstream artifact {downstream_id} not registered in dependency graph"
            )
        self._downstream[upstream_id].add(downstream_id)
        self._upstream[downstream_id].add(upstream_id)
        logger.info(
            f"[ArtifactDepGraph] Added dependency: {upstream_id} → {downstream_id}"
        )

    # ------------------------------------------------------------------
    # Stale 传播（BFS）
    # ------------------------------------------------------------------

    def propagate_stale(self, artifact_id: str, stale_type: str) -> list[str]:
        """
        从 artifact_id 出发，沿下游方向传播 stale 标记。

        规则：
        - hard_stale: 所有直接和间接下游标记 hard_stale
        - soft_stale: 所有直接和间接下游标记 soft_stale（不升级已有的 hard_stale）
        - 幂等：已经是 hard_stale 的节点不会被 soft_stale 降级；
                 已经是目标 stale 类型的节点不会重复处理其子树

        返回所有受影响（状态实际发生变化）的 artifact_id 列表。
        """
        if stale_type not in (HARD_STALE, SOFT_STALE):
            raise ValueError(f"Invalid stale_type: {stale_type}, must be '{HARD_STALE}' or '{SOFT_STALE}'")

        if artifact_id not in self._artifacts:
            logger.warning(
                f"[ArtifactDepGraph] Artifact {artifact_id} not in graph, skipping propagation"
            )
            return []

        affected: list[str] = []
        visited: set[str] = set()
        queue: deque[str] = deque()

        # Seed the BFS with direct downstream of the source artifact
        for downstream_id in self._downstream.get(artifact_id, set()):
            if downstream_id not in visited:
                visited.add(downstream_id)
                queue.append(downstream_id)

        while queue:
            current_id = queue.popleft()
            record = ArtifactStore.get(current_id)
            if record is None:
                logger.warning(
                    f"[ArtifactDepGraph] Artifact {current_id} not found in store, skipping"
                )
                continue

            current_stale = record.stale_status

            # Idempotency: skip if already at the target level or higher
            if stale_type == HARD_STALE:
                if current_stale == HARD_STALE:
                    # Already hard_stale — no need to propagate further from here
                    continue
                # Mark hard_stale (upgrades None or soft_stale)
                ArtifactStore.update_stale_status(current_id, HARD_STALE)
                affected.append(current_id)
            else:
                # soft_stale propagation
                if current_stale in (HARD_STALE, SOFT_STALE):
                    # Do NOT downgrade hard_stale; already soft_stale is a no-op
                    continue
                ArtifactStore.update_stale_status(current_id, SOFT_STALE)
                affected.append(current_id)

            # Continue BFS to downstream
            for downstream_id in self._downstream.get(current_id, set()):
                if downstream_id not in visited:
                    visited.add(downstream_id)
                    queue.append(downstream_id)

        logger.info(
            f"[ArtifactDepGraph] Propagated {stale_type} from {artifact_id}, "
            f"affected {len(affected)} artifacts: {affected}"
        )

        if self._event_stream and affected:
            try:
                self._event_stream.emit("stale_propagation", {
                    "source_artifact_id": artifact_id,
                    "stale_type": stale_type,
                    "affected_count": len(affected),
                    "affected_ids": affected,
                })
            except Exception as e:
                logger.debug(f"[ArtifactDepGraph] Event emission failed: {e}")

        return affected

    # ------------------------------------------------------------------
    # 可交付产物筛选
    # ------------------------------------------------------------------

    def get_deliverable_artifacts(self, task_session_id: str) -> list[str]:
        """
        返回指定 task_session 下所有非 stale 的产物 ID。

        筛选条件：stale_status 为 None（即非 soft_stale 且非 hard_stale）。
        """
        deliverable: list[str] = []
        for aid, tsid in self._artifacts.items():
            if tsid != task_session_id:
                continue
            record = ArtifactStore.get(aid)
            if record is not None and record.stale_status is None:
                deliverable.append(aid)
        return deliverable

    # ------------------------------------------------------------------
    # 移除产物
    # ------------------------------------------------------------------

    def remove_artifact(self, artifact_id: str) -> None:
        """
        从依赖图中移除一个产物及其所有关联边。

        不影响 ArtifactStore 中的持久化记录（仅移除图结构）。
        """
        if artifact_id not in self._artifacts:
            logger.debug(
                f"[ArtifactDepGraph] Artifact {artifact_id} not in graph, nothing to remove"
            )
            return

        # 清理下游引用：从所有上游节点的 _downstream 集合中移除自己
        for upstream_id in self._upstream.get(artifact_id, set()):
            self._downstream.get(upstream_id, set()).discard(artifact_id)

        # 清理上游引用：从所有下游节点的 _upstream 集合中移除自己
        for downstream_id in self._downstream.get(artifact_id, set()):
            self._upstream.get(downstream_id, set()).discard(artifact_id)

        # 移除自身
        del self._artifacts[artifact_id]
        del self._downstream[artifact_id]
        del self._upstream[artifact_id]

        logger.info(f"[ArtifactDepGraph] Removed artifact {artifact_id} from graph")
