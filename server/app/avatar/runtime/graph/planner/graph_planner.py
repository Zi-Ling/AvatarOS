"""
GraphPlanner - Adapter for InteractiveLLMPlanner with Graph Runtime

This module provides an adapter layer that wraps InteractiveLLMPlanner
to work with the Graph Runtime architecture while preserving existing
optimizations (loop detection, filesystem caching, output truncation).

Requirements: 6.1, 19.1, 19.2, 19.3, 19.4, 19.5
"""

from __future__ import annotations
from typing import Optional, Dict, Any, TYPE_CHECKING
import logging

from app.avatar.planner.planners.interactive import InteractiveLLMPlanner
from app.avatar.planner.models import Task, Step
from app.avatar.runtime.graph.planner.prompt_builder import PromptBuilder
from app.avatar.runtime.graph.models.graph_patch import (
    GraphPatch,
    PatchAction,
    PatchOperation,
)
from app.avatar.runtime.graph.models.step_node import StepNode, NodeStatus
import logging

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)


def _estimate_cost(model: str, usage: Dict[str, Any]) -> float:
    """
    用 litellm.cost_per_token() 精确计算 cost（USD）。
    litellm 内置所有主流模型的 input/output 分开定价，精度远高于手动价格表。
    fallback：litellm 不认识的模型用 gpt-4o-mini 价格兜底。
    """
    prompt_tokens = usage.get('prompt_tokens', 0)
    completion_tokens = usage.get('completion_tokens', 0)
    if not prompt_tokens and not completion_tokens:
        return 0.0
    try:
        import litellm
        # litellm 对部分 provider 需要 "provider/model" 格式才能正确 lookup
        # openai 模型（gpt-*）直接用 model name 即可，deepseek/ollama 需要加前缀
        normalized = _normalize_model_name(model)
        input_cost, output_cost = litellm.cost_per_token(
            model=normalized,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        return round(input_cost + output_cost, 8)
    except Exception:
        # fallback：gpt-4o-mini 均价兜底
        total = prompt_tokens + completion_tokens
        return round(total * 0.000375 / 1000, 8)


def _normalize_model_name(model: str) -> str:
    """
    把内部 model name 规范化为 litellm 能识别的格式。
    规则：
    - gpt-* / o1-* / o3-* / text-* → 直接用（openai 不需要前缀）
    - deepseek-* → deepseek/deepseek-*
    - 已有 provider/ 前缀 → 直接用
    - 其他 → 原样（litellm fallback 会处理）
    """
    if not model:
        return "gpt-4o-mini"
    if "/" in model:
        return model  # 已有前缀
    m = model.lower()
    if m.startswith("gpt-") or m.startswith("o1-") or m.startswith("o3-") or m.startswith("text-"):
        return model  # openai 原生格式
    if m.startswith("deepseek-"):
        return f"deepseek/{model}"
    if m.startswith("llama") or m.startswith("mistral") or m.startswith("qwen"):
        return f"ollama/{model}"
    return model


class GraphPlanner:
    """
    Adapter for InteractiveLLMPlanner to work with Graph Runtime.
    
    This class wraps InteractiveLLMPlanner and provides:
    1. ExecutionGraph input support (converts from Task model)
    2. GraphPatch output support (converts from Step model)
    3. Integration with PromptBuilder for prompt generation
    4. Preservation of existing optimizations:
       - Loop detection (similarity > 95% + same action → warning)
       - Filesystem caching (5 second expiry)
       - Output truncation (first 250 + last 300 chars)
    
    Requirements:
    - 6.1: Integrate PromptBuilder for prompt generation
    - 19.1: Support ExecutionGraph input
    - 19.2: Support GraphPatch output
    - 19.3: Preserve loop detection optimization
    - 19.4: Preserve filesystem caching optimization
    - 19.5: Preserve output truncation optimization
    """
    
    def __init__(
        self,
        llm_client: Any,
        capability_registry: Any = None,  # kept for backward compat, unused
        prompt_builder: Optional[PromptBuilder] = None,
    ):
        self.interactive_planner = InteractiveLLMPlanner(llm_client)
        self.prompt_builder = prompt_builder or PromptBuilder()
        logger.info("GraphPlanner initialized")
    
    async def plan_next_step(
        self,
        graph: 'ExecutionGraph',
        env_context: Dict[str, Any],
    ) -> Optional[GraphPatch]:
        """
        Plan the next step for ReAct mode (iterative planning).
        
        This method:
        1. Converts ExecutionGraph to Task model
        2. Calls InteractiveLLMPlanner.next_step()
        3. Converts Step to GraphPatch
        
        Args:
            graph: Current execution graph
            env_context: Environment context (workspace_path, available_skills, etc.)
            
        Returns:
            GraphPatch with ADD_NODE action, or None if finished
            
        Requirements: 6.1, 19.1, 19.2, 19.3, 19.4, 19.5
        """
        # Convert ExecutionGraph to Task model
        task = self._graph_to_task(graph, env_context=env_context)
        
        # Call InteractiveLLMPlanner (preserves all optimizations)
        step = await self.interactive_planner.next_step(task, env_context)

        # 读取本次 LLM 调用的 usage（由 _call_llm 缓存）
        usage = getattr(self.interactive_planner, '_last_usage', {}) or {}
        tokens_used = usage.get('total_tokens', 0)
        cost_usd = _estimate_cost(
            model=getattr(self.interactive_planner._llm.config, 'model', ''),
            usage=usage,
        )

        # Convert Step to GraphPatch
        if step is None:
            # Task is finished
            return GraphPatch(
                actions=[
                    PatchAction(
                        operation=PatchOperation.FINISH,
                    )
                ],
                reasoning="Task completed successfully",
                metadata={"tokens_used": tokens_used, "cost": cost_usd},
            )
        
        # Create ADD_NODE action
        patch = self._step_to_patch(step, graph)
        patch.metadata["tokens_used"] = tokens_used
        patch.metadata["cost"] = cost_usd
        return patch
    
    def _graph_to_task(self, graph: 'ExecutionGraph', env_context: Optional[Dict[str, Any]] = None) -> Task:
        """
        Convert ExecutionGraph to Task model.
        
        This enables InteractiveLLMPlanner to work with Graph Runtime.
        
        Args:
            graph: ExecutionGraph to convert
            
        Returns:
            Task model compatible with InteractiveLLMPlanner
        """
        # Convert StepNodes to Steps
        steps = []
        for node_id, node in graph.nodes.items():
            step = Step(
                id=node.id,
                order=len(steps),
                skill_name=node.capability_name,
                params=node.params,
                description=node.metadata.get("description", ""),
            )
            
            # Set step status and result based on node status
            if node.status == NodeStatus.SUCCESS:
                from app.avatar.planner.models import StepStatus, StepResult
                step.status = StepStatus.SUCCESS
                # 按优先级提取输出：stdout > output > content > 整个 outputs dict
                # 与 _execution_graph_to_task 保持一致
                outputs = node.outputs or {}
                output_val = (
                    outputs.get("stdout")
                    or outputs.get("output")
                    or outputs.get("content")
                    or outputs
                )
                # Include output type metadata so planner knows the actual data shape
                # when generating downstream code (prevents type mismatch errors)
                _output_type = type(output_val).__name__
                _output_contract = (node.metadata or {}).get("output_contract")
                _output_schema = (node.metadata or {}).get("output_schema")
                _type_hint = ""
                if _output_schema:
                    _kind = _output_schema.get("semantic_kind", "")
                    _fields = _output_schema.get("fields", [])
                    _field_summary = ", ".join(
                        f"{f['field_name']}:{f['field_type']}" for f in _fields[:5]
                    )
                    _type_hint = f" [output_kind={_kind}, fields={{{_field_summary}}}, python_type={_output_type}]"
                elif _output_contract:
                    _vk = getattr(_output_contract, "value_kind", None)
                    if _vk:
                        _type_hint = f" [output_type={_vk.value if hasattr(_vk, 'value') else _vk}, python_type={_output_type}]"
                    else:
                        _type_hint = f" [python_type={_output_type}]"
                else:
                    _type_hint = f" [python_type={_output_type}]"
                step.result = StepResult(
                    success=True,
                    output=output_val,
                )
                # Append type hint to description so planner sees it
                if step.description:
                    step.description = step.description + _type_hint
                else:
                    step.description = f"output{_type_hint}"
            elif node.status == NodeStatus.FAILED:
                from app.avatar.planner.models import StepStatus, StepResult
                step.status = StepStatus.FAILED
                _err_msg = node.error_message or "Unknown error"
                # Consume PlanningHint from env_context if available
                _err_classification = ""
                _ctx = env_context or {}
                _hints = _ctx.get("planning_hints", [])
                _node_hint = None
                for h in _hints:
                    if isinstance(h, dict) and h.get("node_id") == node.id:
                        _node_hint = h
                        break
                if _node_hint:
                    _ec = _node_hint.get("error_class", "")
                    _ecode = _node_hint.get("error_code", "")
                    _fix = _node_hint.get("suggested_fix", "")
                    _err_classification = f" [error_class={_ec}, error_code={_ecode}]"
                    if _fix:
                        _err_classification += f" [fix_hint={_fix[:200]}]"
                # No fallback: raw exception stack parsing removed.
                # PlanningHint is the sole structured error context source.
                # When no hint is available the planner sees only the raw
                # error_message, which is sufficient for LLM-based reasoning.
                # Append type_mismatch_hint if present
                _tmh = _ctx.get("type_mismatch_hint")
                if _tmh and isinstance(_tmh, dict):
                    _err_classification += f" [type_mismatch_hint={_tmh}]"
                # Append envelope_targets if present
                _et = _ctx.get("envelope_targets")
                if _et:
                    _err_classification += f" [envelope_targets={_et}]"
                step.result = StepResult(
                    success=False,
                    error=_err_msg + _err_classification,
                )
            elif node.status == NodeStatus.RUNNING:
                from app.avatar.planner.models import StepStatus
                step.status = StepStatus.RUNNING
            else:
                from app.avatar.planner.models import StepStatus
                step.status = StepStatus.PENDING
            
            steps.append(step)
        
        # Create Task
        task = Task(
            id=str(graph.id),
            goal=graph.goal,
            steps=steps,
            intent_id=None,  # No intent_id for graph-based tasks
        )
        
        return task
    
    def _step_to_patch(self, step: Step, graph: 'ExecutionGraph') -> GraphPatch:
        """
        Convert Step to GraphPatch.
        
        This creates an ADD_NODE action from the Step returned by
        InteractiveLLMPlanner.
        
        Args:
            step: Step from InteractiveLLMPlanner
            graph: Current execution graph
            
        Returns:
            GraphPatch with ADD_NODE action
        """
        # Create StepNode from Step
        node = StepNode(
            id=step.id,
            capability_name=step.skill_name,
            params=step.params,
            status=NodeStatus.PENDING,
            metadata={"description": step.description},
        )
        
        # Create ADD_NODE action
        action = PatchAction(
            operation=PatchOperation.ADD_NODE,
            node=node,
        )
        
        # Create GraphPatch
        patch = GraphPatch(
            actions=[action],
            reasoning=step.description,
        )
        
        return patch
    
    async def plan_complete_graph(
        self,
        goal: str,
        env_context: Dict[str, Any],
    ) -> GraphPatch:
        """
        Plan complete graph for DAG mode (one-shot planning).
        
        Delegates to DAGPlanner for complete graph generation.
        
        Args:
            goal: High-level goal description
            env_context: Environment context
            
        Returns:
            GraphPatch with all ADD_NODE and ADD_EDGE actions
            
        Requirements: 6.4, 20.1, 20.2, 20.3, 20.4
        """
        from app.avatar.runtime.graph.planner.dag_planner import DAGPlanner

        dag_planner = DAGPlanner(
            llm_client=self.interactive_planner._llm,
            prompt_builder=self.prompt_builder,
        )
        
        # Plan complete graph
        return await dag_planner.plan_complete_graph(goal, env_context)
    
    async def plan_repair(
        self,
        graph: 'ExecutionGraph',
        failed_node_id: str,
        error_message: str,
        env_context: Dict[str, Any],
    ) -> GraphPatch:
        """
        Plan repair for REPAIR mode (error recovery).
        
        This method:
        1. Generates REPAIR prompt using PromptBuilder
        2. Calls LLM to generate recovery plan
        3. Parses response into GraphPatch with recovery actions
        
        Integrates with:
        - CodeRepairManager: For python.run error fixes
        - Replanner: For task replanning logic
        
        Args:
            graph: Current execution graph
            failed_node_id: ID of the failed node
            error_message: Error message from the failure
            env_context: Environment context
            
        Returns:
            GraphPatch with recovery actions
            
        Requirements: 10.1, 10.2, 10.3, 10.4
        """
        from app.avatar.runtime.graph.runtime.graph_runtime import ExecutionResult
        
        # Create failure context
        failed_node = graph.nodes.get(failed_node_id)
        if not failed_node:
            raise ValueError(f"Failed node not found: {failed_node_id}")
        
        # Count completed/failed/skipped nodes
        completed_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS)
        failed_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.FAILED)
        skipped_nodes = sum(1 for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED)
        
        failure_context = ExecutionResult(
            success=False,
            final_status="failed",
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            skipped_nodes=skipped_nodes,
            execution_time=0.0,
            error_message=error_message,
        )
        
        # Generate repair prompt
        prompt = self.prompt_builder.build_repair_prompt(
            goal=graph.goal,
            graph=graph,
            failure_context=failure_context,
            failed_node_id=failed_node_id,
            error_message=error_message,
        )
        
        # Call LLM (run sync call in thread pool to avoid blocking event loop)
        import asyncio
        loop = asyncio.get_event_loop()
        raw_response = await loop.run_in_executor(None, self.interactive_planner._call_llm, prompt)
        
        # Parse response
        try:
            data = self.interactive_planner._parse_json(raw_response)
        except Exception as e:
            logger.error(f"Failed to parse repair response: {e}")
            raise ValueError(f"LLM repair output malformed: {e}\nRaw: {raw_response}")
        
        # Convert to GraphPatch
        actions = []
        for action_data in data.get("actions", []):
            operation_str = action_data.get("operation")
            
            # Normalize operation string to lowercase (handle both "ADD_NODE" and "add_node")
            if operation_str:
                operation_str = operation_str.lower()
            
            try:
                operation = PatchOperation(operation_str)
            except ValueError:
                logger.warning(f"Unknown operation in repair: {operation_str}, skipping")
                continue
            
            if operation == PatchOperation.ADD_NODE:
                node_data = action_data.get("node")
                if not node_data:
                    continue
                
                node = StepNode(
                    id=node_data.get("id"),
                    capability_name=node_data.get("capability_name"),
                    params=node_data.get("params", {}),
                    status=NodeStatus.PENDING,
                    metadata=node_data.get("metadata", {}),
                )
                
                actions.append(PatchAction(
                    operation=operation,
                    node=node,
                ))
            
            elif operation == PatchOperation.ADD_EDGE:
                edge_data = action_data.get("edge")
                if not edge_data:
                    continue
                
                from app.avatar.runtime.graph.models.data_edge import DataEdge
                
                edge = DataEdge(
                    source_node=edge_data.get("source_node"),
                    source_field=edge_data.get("source_field", "output"),
                    target_node=edge_data.get("target_node"),
                    target_param=edge_data.get("target_param"),
                    transformer_name=edge_data.get("transformer_name"),
                    optional=edge_data.get("optional", False),
                )
                
                actions.append(PatchAction(
                    operation=operation,
                    edge=edge,
                ))
        
        return GraphPatch(
            actions=actions,
            reasoning=data.get("analysis", "") + " | " + data.get("recovery_strategy", ""),
        )
