# server/app/services/workflow/dag_scheduler.py
"""
DAG 拓扑排序 + 依赖推进 + 跳过传播 + 输入满足性检查。

正确性属性：P4（拓扑序执行）、P5（槽位并发限制）、P8（跳过传播正确性）。
"""
from __future__ import annotations

import graphlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .condition_evaluator import ConditionEvaluator
from .models import (
    StepFailurePolicy,
    StepRunStatus,
    WorkflowEdgeDef,
    WorkflowStepDef,
    WorkflowStepRun,
)

logger = logging.getLogger(__name__)


@dataclass
class DAGSchedulerResult:
    ready_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
    workflow_completed: bool = False
    workflow_failed: bool = False


class WorkflowDAGScheduler:
    """DAG 拓扑排序 + 依赖推进"""

    def __init__(self, condition_evaluator: ConditionEvaluator | None = None):
        self._condition_evaluator = condition_evaluator or ConditionEvaluator()

    # ------------------------------------------------------------------
    # 拓扑排序
    # ------------------------------------------------------------------

    @staticmethod
    def get_topological_order(
        steps: list[dict], edges: list[dict]
    ) -> list[str]:
        """返回拓扑排序结果（P4）。"""
        step_ids = {s["step_id"] for s in steps}
        graph: dict[str, set[str]] = {sid: set() for sid in step_ids}
        for e in edges:
            src, tgt = e["source_step_id"], e["target_step_id"]
            if src in step_ids and tgt in step_ids:
                graph[tgt].add(src)
        ts = graphlib.TopologicalSorter(graph)
        return list(ts.static_order())

    # ------------------------------------------------------------------
    # 辅助：构建索引
    # ------------------------------------------------------------------

    @staticmethod
    def _build_predecessor_index(
        steps: list[dict], edges: list[dict]
    ) -> dict[str, list[dict]]:
        """构建 step_id → 入边列表 的索引。"""
        index: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            index[e["target_step_id"]].append(e)
        return dict(index)

    @staticmethod
    def _build_successor_index(
        edges: list[dict],
    ) -> dict[str, list[dict]]:
        """构建 step_id → 出边列表 的索引。"""
        index: dict[str, list[dict]] = defaultdict(list)
        for e in edges:
            index[e["source_step_id"]].append(e)
        return dict(index)

    @staticmethod
    def _get_step_def(steps: list[dict], step_id: str) -> dict | None:
        for s in steps:
            if s["step_id"] == step_id:
                return s
        return None

    # ------------------------------------------------------------------
    # get_ready_steps
    # ------------------------------------------------------------------

    def get_ready_steps(
        self,
        steps: list[dict],
        edges: list[dict],
        step_runs: dict[str, WorkflowStepRun],
        step_outputs: dict[str, dict[str, Any]],
        max_parallel: int,
        global_failure_policy: str = "fail_fast",
    ) -> tuple[list[str], list[str]]:
        """
        返回 (ready_step_ids, newly_skipped_step_ids)。

        分离"前驱放行"和"输入满足性"两个判断（P4, P5）。
        """
        pred_index = self._build_predecessor_index(steps, edges)
        running_count = sum(
            1 for sr in step_runs.values() if sr.status == StepRunStatus.RUNNING
        )
        available_slots = max(0, max_parallel - running_count)

        ready: list[str] = []
        skipped: list[str] = []

        for s in steps:
            sid = s["step_id"]
            sr = step_runs.get(sid)
            if not sr or sr.status != StepRunStatus.PENDING:
                continue

            incoming = pred_index.get(sid, [])

            # 1. 前驱放行检查：所有前驱必须已终止
            if not self._predecessors_released(incoming, step_runs, global_failure_policy):
                continue

            # 2. 输入满足性检查
            if not self._inputs_satisfied(sid, s, incoming, step_runs, step_outputs):
                skipped.append(sid)
                continue

            # 3. 条件求值
            condition_data = s.get("condition")
            if condition_data:
                from .models import ConditionExpr
                cond = ConditionExpr.model_validate(condition_data)
                if not self._condition_evaluator.evaluate(cond, step_outputs):
                    skipped.append(sid)
                    continue

            ready.append(sid)

        # P5: 并发限制
        ready = ready[:available_slots]
        return ready, skipped

    def _predecessors_released(
        self,
        incoming_edges: list[dict],
        step_runs: dict[str, WorkflowStepRun],
        global_failure_policy: str,
    ) -> bool:
        """前驱放行检查：所有前驱必须已终止（success/skipped/failed+continue）。"""
        for e in incoming_edges:
            src_id = e["source_step_id"]
            src_run = step_runs.get(src_id)
            if not src_run:
                return False
            if src_run.status in (StepRunStatus.SUCCESS, StepRunStatus.SKIPPED, StepRunStatus.CANCELLED):
                continue
            if src_run.status == StepRunStatus.FAILED:
                # failed 前驱只有在 continue 策略下才算放行
                # 检查步骤级策略，没有则用全局策略
                # 注意：这里我们无法直接访问 step_def 的 failure_policy，
                # 但 failed 步骤的策略已经在 on_step_completed 中处理过了，
                # 如果走到这里说明策略是 continue（否则工作流已终止）
                continue
            return False  # pending / running
        return True

    def _inputs_satisfied(
        self,
        step_id: str,
        step_def: dict,
        incoming_edges: list[dict],
        step_runs: dict[str, WorkflowStepRun],
        step_outputs: dict[str, dict[str, Any]],
    ) -> bool:
        """
        输入满足性检查（与放行检查分离）。

        对每条非 optional edge：
        - 源步骤 success → 输入满足
        - 源步骤 failed/skipped + edge.optional=True → 可缺失
        - 源步骤 failed/skipped + edge.optional=False → 检查静态默认值
        - 无默认值 → input_unsatisfied
        """
        static_params = step_def.get("params", {})

        for e in incoming_edges:
            src_id = e["source_step_id"]
            src_run = step_runs.get(src_id)
            if not src_run:
                continue

            if src_run.status == StepRunStatus.SUCCESS:
                continue  # 输入可用

            # 源步骤 failed 或 skipped
            is_optional = e.get("optional", False)
            if is_optional:
                continue  # 弱依赖，可缺失

            # 强依赖但源步骤未成功 → 检查是否有静态默认值
            target_key = e["target_param_key"]
            if target_key in static_params:
                continue  # 有静态默认值兜底

            # 无默认值 → input_unsatisfied
            logger.info(
                f"[DAGScheduler] Step {step_id} input_unsatisfied: "
                f"edge from {src_id}.{e['source_output_key']} → {target_key}, "
                f"source status={src_run.status}, no default"
            )
            return False

        return True

    # ------------------------------------------------------------------
    # 跳过传播（P8）
    # ------------------------------------------------------------------

    def propagate_skip(
        self,
        skipped_step_id: str,
        steps: list[dict],
        edges: list[dict],
        step_runs: dict[str, WorkflowStepRun],
    ) -> list[str]:
        """
        BFS 跳过传播。

        规则：
        - 只沿强依赖链（optional=False）传播
        - 下游步骤的所有必需前驱中，至少一个成功 → 不跳过
        - 下游步骤的所有必需前驱都是 skipped/failed → 跳过
        """
        succ_index = self._build_successor_index(edges)
        pred_index = self._build_predecessor_index(steps, edges)
        newly_skipped: list[str] = []
        queue = [skipped_step_id]

        while queue:
            current = queue.pop(0)
            for out_edge in succ_index.get(current, []):
                if out_edge.get("optional", False):
                    continue  # 弱依赖不传播

                downstream_id = out_edge["target_step_id"]
                ds_run = step_runs.get(downstream_id)
                if not ds_run or ds_run.status != StepRunStatus.PENDING:
                    continue

                # 检查该下游步骤的所有必需前驱
                required_preds = [
                    e["source_step_id"]
                    for e in pred_index.get(downstream_id, [])
                    if not e.get("optional", False)
                ]

                has_success = any(
                    step_runs.get(pid) and step_runs[pid].status == StepRunStatus.SUCCESS
                    for pid in required_preds
                )

                if has_success:
                    continue  # 至少一个必需前驱成功，不跳过

                # 所有必需前驱都是 skipped/failed → 跳过
                all_terminal = all(
                    step_runs.get(pid) and step_runs[pid].status in (
                        StepRunStatus.SKIPPED, StepRunStatus.FAILED, StepRunStatus.CANCELLED
                    )
                    for pid in required_preds
                )

                if all_terminal:
                    newly_skipped.append(downstream_id)
                    # 更新 step_runs 状态以支持传递性 BFS
                    ds_run.status = StepRunStatus.SKIPPED
                    queue.append(downstream_id)

        return newly_skipped

    # ------------------------------------------------------------------
    # on_step_completed
    # ------------------------------------------------------------------

    def on_step_completed(
        self,
        completed_step_id: str,
        success: bool,
        steps: list[dict],
        edges: list[dict],
        step_runs: dict[str, WorkflowStepRun],
        step_outputs: dict[str, dict[str, Any]],
        max_parallel: int,
        global_failure_policy: str = "fail_fast",
        step_failure_policy: str | None = None,
    ) -> DAGSchedulerResult:
        """步骤完成回调。"""
        result = DAGSchedulerResult()

        effective_policy = step_failure_policy or global_failure_policy

        if not success:
            if effective_policy == StepFailurePolicy.FAIL_FAST:
                result.workflow_failed = True
                return result
            # continue 或 retry 已耗尽 → 传播跳过
            skipped = self.propagate_skip(
                completed_step_id, steps, edges, step_runs
            )
            result.skipped_steps = skipped

        # 获取新的 ready 步骤
        ready, condition_skipped = self.get_ready_steps(
            steps, edges, step_runs, step_outputs,
            max_parallel, global_failure_policy,
        )
        result.ready_steps = ready
        result.skipped_steps.extend(condition_skipped)

        # 检查是否所有步骤都已终止
        all_terminal = all(
            sr.status in (
                StepRunStatus.SUCCESS, StepRunStatus.FAILED,
                StepRunStatus.SKIPPED, StepRunStatus.CANCELLED,
                "success", "failed", "skipped", "cancelled",
            )
            for sr in step_runs.values()
        )
        if all_terminal:
            result.workflow_completed = True
            # 只在 fail_fast 策略下标记工作流失败
            # continue 策略下的 failed 步骤已被处理（下游已跳过），不算工作流失败
            if global_failure_policy == StepFailurePolicy.FAIL_FAST:
                has_failed = any(
                    sr.status in (StepRunStatus.FAILED, "failed")
                    for sr in step_runs.values()
                )
                if has_failed:
                    result.workflow_failed = True

        return result
