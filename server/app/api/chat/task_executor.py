# app/api/chat/task_executor.py
"""
任务执行逻辑：后台任务执行、结果格式化、Socket 推送
"""
import inspect
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from app.avatar.intent.models import IntentSpec, IntentDomain
from app.avatar.memory.manager import MemoryManager
from app.router.param_extractor import ParameterExtractor
from app.io.manager import SocketManager

logger = logging.getLogger(__name__)
socket_manager = SocketManager.get_instance()


def _detect_language(text: str) -> str:
    """检测用户语言（简单启发式）"""
    return "zh" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en"


_reference_resolver = None


def _get_reference_resolver():
    global _reference_resolver
    if _reference_resolver is None:
        from app.avatar.runtime.context.reference_resolver import ReferenceResolver
        _reference_resolver = ReferenceResolver()
    return _reference_resolver


def _classify_execution_error(error: Exception) -> str:
    """
    将执行异常分类为：
    - "infra"：基础设施错误（沙箱断连、超时、资源不足），LLM 无法提供额外帮助
    - "code"：代码执行错误（Python traceback），LLM 可以分析并给出修复建议
    - "unknown"：其他未知错误
    """
    err_str = str(error).lower()
    err_type = type(error).__name__

    # 基础设施错误：网络/连接类
    infra_keywords = (
        "remoteDisconnected", "connectionerror", "connectionaborted",
        "remotedisconnected", "protocolerror", "connectionreset",
        "brokenpipe", "sandbox_dead", "sandbox_timeout", "no healthy container",
    )
    if any(k.lower() in err_str for k in infra_keywords):
        return "infra"
    if err_type in ("ConnectionError", "RemoteDisconnected", "ProtocolError",
                    "BrokenPipeError", "ConnectionResetError", "SandboxFailure"):
        return "infra"

    # 代码错误：Python traceback 特征
    code_keywords = ("traceback", "syntaxerror", "nameerror", "typeerror",
                     "valueerror", "importerror", "modulenotfounderror",
                     "attributeerror", "indexerror", "keyerror", "exit code")
    if any(k in err_str for k in code_keywords):
        return "code"

    return "unknown"


async def _analyze_code_error(llm_client, goal: str, error_detail: str, user_language: str = "zh") -> str:
    """用 LLM 分析代码执行错误，给出可能原因和修复建议"""
    # 截断 error_detail，避免 prompt 过长
    truncated = error_detail[:1500] if len(error_detail) > 1500 else error_detail

    if user_language == "zh":
        prompt = f"""用户想要完成的任务：{goal}

执行时遇到以下错误：
```
{truncated}
```

请分析：
1. 错误的可能原因（1-2句）
2. 具体的修复建议（可操作的步骤）

要求：简洁、直接，不要重复错误内容，用中文回复"""
    else:
        prompt = f"""Task: {goal}

Execution error:
```
{truncated}
```

Analyze: 1) likely cause (1-2 sentences), 2) specific fix steps. Be concise."""

    try:
        if inspect.iscoroutinefunction(llm_client.call):
            analysis = await llm_client.call(prompt)
        else:
            analysis = llm_client.call(prompt)
        return analysis.strip()
    except Exception as e:
        logger.error(f"[ErrorAnalysis] LLM analysis failed: {e}")
        return ""


async def generate_capability_explanation(
    llm_client, goal: str, top_skills: list[str],
    relevance_score: float, user_language: str = "zh",
) -> str:
    """能力解释器：当系统无相关技能时，生成友好的回复"""
    top_skills_str = ", ".join(top_skills[:3]) if top_skills else "无匹配技能"
    
    if user_language == "zh":
        prompt = f"""用户想要：{goal}

系统能力分析：
- 最相关的技能：{top_skills_str}
- 相似度评分：{relevance_score:.2f}（阈值：0.50）
- 判断：相似度过低，当前技能库无法完成此任务

请生成一个友好且有帮助的回复（2-3句话）：
1. 承认并理解用户的需求
2. 坦诚说明当前系统还不支持此功能
3. 如果可能，建议替代方式或相关功能

要求：语气友好、专业，不要显示技术细节，用中文回复"""
    else:
        prompt = f"""User wants: {goal}
Most relevant skills: {top_skills_str}, score: {relevance_score:.2f} (threshold: 0.50)
Generate a friendly 2-3 sentence response acknowledging the need and explaining the system doesn't support it yet."""
    
    try:
        if inspect.iscoroutinefunction(llm_client.call):
            explanation = await llm_client.call(prompt)
        else:
            explanation = llm_client.call(prompt)
        return explanation.strip()
    except Exception as e:
        logger.error(f"Failed to generate capability explanation: {e}")
        if user_language == "zh":
            return f"我理解你想{goal}，但我目前还不支持这个功能。我可以帮你处理文件操作、网页浏览、文档处理等任务。"
        return f"I understand you want to {goal}, but I don't support this feature yet."


def _extract_step_result(run_record):
    """从 run_record 提取最后一步的结果，返回 (success, output_val, real_b64_image, target_obj)"""
    real_b64_image = None
    target_obj = None
    
    if not run_record.steps:
        return False, None, None, None
    
    last_step = run_record.steps[-1]
    
    # Handle both object and dict
    step_result = None
    if isinstance(last_step, dict):
        step_result = last_step.get("result")
    elif hasattr(last_step, "result"):
        step_result = last_step.result
    elif hasattr(last_step, "output_result"):
        step_result = last_step.output_result
    
    # Unwrap nested dict
    if isinstance(step_result, dict) and "value" in step_result and isinstance(step_result["value"], dict):
        step_result = step_result["value"]
    
    if not step_result:
        return False, None, None, None
    
    # Determine success
    success = step_result.get("success", False) if isinstance(step_result, dict) else getattr(step_result, "success", False)
    
    if not success:
        return False, None, None, None
    
    # Extract output
    output_val = _extract_output_value(step_result)
    if output_val is None:
        return True, None, None, None
    
    # Extract image
    if isinstance(output_val, dict):
        real_b64_image = output_val.get("base64_image")
    elif hasattr(output_val, "base64_image"):
        real_b64_image = getattr(output_val, "base64_image", None)
    
    # Build safe output for display
    target_obj = _build_safe_output(output_val)
    
    return True, output_val, real_b64_image, target_obj


def _extract_output_value(step_result):
    """从 step_result 提取有意义的输出值"""
    if isinstance(step_result, dict):
        output_data = {k: v for k, v in step_result.items() if k not in ("success", "message", "error")}
        for key in ("stdout", "items", "output", "content"):
            if key in output_data and output_data[key]:
                return output_data[key]
        return output_data if output_data else None
    
    if hasattr(step_result, "model_dump"):
        data = step_result.model_dump()
        output_data = {k: v for k, v in data.items() if k not in ("success", "message", "error")}
        for key in ("stdout", "items", "output", "content"):
            if key in output_data and output_data[key]:
                return output_data[key]
        return output_data if output_data else None
    
    return str(step_result)


def _build_safe_output(output_val):
    """构建安全的输出对象（遮蔽 base64 图片）"""
    safe_output = None
    b64_placeholder = "<<BASE64_IMAGE_CONTENT>>"
    
    if isinstance(output_val, dict):
        safe_output = output_val.copy()
    elif hasattr(output_val, "model_dump"):
        safe_output = output_val.model_dump()
    elif hasattr(output_val, "__dict__"):
        safe_output = output_val.__dict__.copy()
    
    if safe_output and isinstance(safe_output, dict) and safe_output.get("base64_image"):
        safe_output["base64_image"] = b64_placeholder
    
    target_obj = safe_output if safe_output is not None else output_val
    if not isinstance(target_obj, (dict, list)):
        target_obj = {"result": str(target_obj)}
    
    return target_obj


def build_task_result_summary(
    run_record,
    goal: str,
    target_obj: dict = None,
    final_summary: str = None,
) -> dict:
    """
    统一的任务结果摘要提炼器。
    产出固定 schema 的 dict，供 SessionContext 存储和 Planner prompt 注入使用。

    Schema:
        task_id       - run record id
        goal          - 本次任务目标
        status        - success | failed | partial
        output_type   - file | text | json | none
        output_path   - 文件路径（如有）
        output_value  - 核心输出值（截断至 500 字符）
        summary       - 人类可读摘要（截断至 300 字符）
        updated_at    - ISO 时间戳
    """
    status = run_record.status if run_record.status in ("completed", "failed") else "partial"
    if status == "completed":
        status = "success"

    output_path = ""
    output_value = ""
    output_type = "none"

    if target_obj and isinstance(target_obj, dict):
        # 1. 优先提取文件路径
        for path_key in ("path", "output_path", "file_path", "current_url", "url"):
            if target_obj.get(path_key):
                output_path = str(target_obj[path_key])
                output_type = "file"
                break

        # 2. 提取核心文本值（优先级：stdout > output > content > items > 整体 JSON）
        raw_value = None
        for val_key in ("stdout", "output", "content", "text", "result"):
            if target_obj.get(val_key):
                raw_value = target_obj[val_key]
                break

        if raw_value is None and output_type != "file":
            # fallback: 整体 JSON，去掉 base64
            safe = {k: v for k, v in target_obj.items()
                    if k not in ("base64_image",) and v not in (None, "", [], {})}
            if safe:
                raw_value = safe

        if raw_value is not None:
            if isinstance(raw_value, (dict, list)):
                output_type = "json"
                raw_str = json.dumps(raw_value, ensure_ascii=False)
            else:
                raw_str = str(raw_value)
                output_type = "text" if output_type == "none" else output_type

            # 截断至 500 字符，保留首尾
            if len(raw_str) > 500:
                output_value = raw_str[:300] + "\n...[truncated]...\n" + raw_str[-150:]
            else:
                output_value = raw_str

    # 3. summary：优先用 final_summary 的纯文本部分（去掉 image block），截断至 300 字符
    summary = ""
    if final_summary:
        # 去掉 ```image ... ``` 块
        clean = re.sub(r'```image\n.*?\n```', '', final_summary, flags=re.DOTALL).strip()
        summary = clean[:300] if len(clean) > 300 else clean

    return {
        "task_id": str(getattr(run_record, "id", "")),
        "goal": goal,
        "status": status,
        "output_type": output_type,
        "output_path": output_path,
        "output_value": output_value,
        "summary": summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def execute_task(
    avatar_router, decision, user_message: str, session_id: str,
    prefix_content: str, history: list = None, memory_manager: MemoryManager = None,
):
    """后台任务执行逻辑（Fire-and-Forget，结果通过 Socket 推送）"""
    from app.api.chat.cancellation import get_cancellation_manager
    from .session import save_message_to_session
    
    if not decision.can_execute:
        # 无法执行 — 生成能力解释并推送
        user_language = _detect_language(user_message)
        explanation_msg = None
        
        if decision.relevance_score > 0 and decision.top_skills:
            try:
                explanation = await generate_capability_explanation(
                    llm_client=avatar_router.llm,
                    goal=decision.goal or user_message,
                    top_skills=decision.top_skills,
                    relevance_score=decision.relevance_score,
                    user_language=user_language,
                )
                explanation_msg = f"{prefix_content}💡 {explanation}"
            except Exception as e:
                logger.error(f"Capability explanation failed: {e}")
        
        if not explanation_msg:
            missing_info = ""
            if decision.missing_skills:
                missing_info = f"\n\n缺少的技能：{', '.join(decision.missing_skills)}"
            explanation_msg = f"{prefix_content}💡 {decision.llm_explanation}{missing_info}"
        
        # 保存并推送
        save_message_to_session(session_id, "assistant", explanation_msg)
        await socket_manager.emit("server_event", {
            "type": "task.summary",
            "payload": {"session_id": session_id, "content": explanation_msg},
        })
        return

    # 可执行的任务
    try:
        runtime = avatar_router.runtime
        resolved_goal = decision.goal or user_message
        artifact_context = []
        
        # Artifact 引用解析
        if memory_manager and session_id:
            try:
                from app.avatar.runtime.artifact.resolver import resolve_artifact_references
                resolved = await resolve_artifact_references(
                    text=resolved_goal, session_id=session_id, memory_manager=memory_manager,
                )
                if resolved.success and resolved.confidence > 0.5:
                    logger.info(f"[ArtifactResolver] Resolved {len(resolved.artifacts)} artifacts (confidence={resolved.confidence:.2f})")
                    artifact_context = resolved.artifacts
            except Exception as e:
                logger.warning(f"[ArtifactResolver] Failed: {e}")
        
        # 构建 IntentSpec
        if decision.intent_spec:
            initial_intent = decision.intent_spec
            initial_intent.goal = resolved_goal
            initial_intent.raw_user_input = user_message
            initial_intent.metadata.update({
                "source": "router_v2", "session_id": session_id,
                "chat_history": history or [], "artifact_context": artifact_context,
                "router_scored_skills": decision.scored_skills,
                "is_complex": decision.is_complex,
            })
        else:
            initial_intent = IntentSpec(
                id=str(uuid.uuid4()), goal=resolved_goal,
                intent_type="unknown", domain=IntentDomain.OTHER,
                raw_user_input=user_message,
                metadata={
                    "source": "router_v2", "session_id": session_id,
                    "chat_history": history or [], "artifact_context": artifact_context,
                    "router_scored_skills": decision.scored_skills,
                    "is_complex": decision.is_complex,
                },
            )

        # Reference Resolution: 结构化指代消解，按优先级从 history 绑定引用对象
        # 不依赖正则/指代词，只要 history 有 assistant 消息就尝试绑定，confidence 决定是否使用
        resolver = _get_reference_resolver()
        resolution = resolver.resolve(history or [])
        if resolution.resolved and resolution.best and resolution.best.confidence >= 0.5:
            resolved_inputs = resolution.to_env_dict()

            # IntentSpec typed slots 优先覆盖：只有路径类 slot 才覆盖
            # content 永远来自 ReferenceResolver（历史消息），不从当前输入提取
            intent_slots = initial_intent.params or {}
            if intent_slots.get("file_path"):
                resolved_inputs["file_path"] = intent_slots["file_path"]
                resolved_inputs["path_ref"] = {
                    "confidence": 1.0,
                    "source_type": "intent_slot",
                    "source_id": "current_turn",
                    "resolver_rule": "intent_extractor.file_path_slot",
                    "file_path": intent_slots["file_path"],
                }
            if intent_slots.get("target_path") and not resolved_inputs.get("path_ref"):
                resolved_inputs["path_ref"] = {
                    "confidence": 1.0,
                    "source_type": "intent_slot",
                    "source_id": "current_turn",
                    "resolver_rule": "intent_extractor.target_path_slot",
                    "file_path": intent_slots["target_path"],
                }

            initial_intent.metadata["resolved_inputs"] = resolved_inputs
            typed_keys = [k for k in ("content_ref", "path_ref") if resolved_inputs.get(k)]
            logger.info(
                f"[ReferenceResolver] Bound: source={resolved_inputs['source_type']}, "
                f"confidence={resolved_inputs['confidence']:.2f}, "
                f"typed_refs={typed_keys}"
            )

        # Parameter Extraction: 从自然语言中提取结构化参数，减轻 Planner 负担
        if decision.top_skills:
            try:
                skill_schemas = {}
                from app.avatar.skills.registry import SkillRegistry
                registry = SkillRegistry()
                all_descs = registry.describe_skills()
                for sk in decision.top_skills:
                    if sk in all_descs:
                        skill_schemas[sk] = all_descs[sk]

                extracted = ParameterExtractor.extract(
                    user_input=user_message,
                    goal=resolved_goal,
                    top_skills=decision.top_skills,
                    skill_schemas=skill_schemas,
                )
                if extracted:
                    initial_intent.params.update(extracted)
                    initial_intent.metadata["extracted_params"] = extracted
            except Exception as pe:
                logger.debug(f"[ParamExtractor] Non-fatal extraction error: {pe}")

        # 注册取消事件（生命周期绑定 task_id，task 真正完成后才注销）
        cancellation_mgr = get_cancellation_manager()
        task_cancel_event = cancellation_mgr.register_task(initial_intent.id, session_id)
        logger.info(f"[TaskExecution] 已注册任务: {initial_intent.id}")

        task_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        try:
            run_record = await runtime.run_intent(
                initial_intent, task_mode=decision.task_mode, cancel_event=task_cancel_event,
                on_graph_created=lambda gid: cancellation_mgr.alias_task(gid, initial_intent.id),
            )
            # 任务执行完成后，向前端推送完整的执行计划和每个步骤的结果
            await _emit_plan_and_steps(run_record, initial_intent, session_id)
        finally:
            # 无论成功/失败/取消，task 完成后立即注销，释放资源
            cancellation_mgr.unregister_task(initial_intent.id)
            logger.info(f"[TaskExecution] 已注销任务: {initial_intent.id}")

    except RuntimeError as e:
        return await _handle_planning_failure(
            e, avatar_router, decision, user_message, session_id, prefix_content,
        )
    except Exception as e:
        # 兜底：防止 fire-and-forget 任务异常丢失
        logger.error(f"[TaskExecution] Unexpected error for goal='{decision.goal}': {e}", exc_info=True)
        from .session import save_message_to_session
        user_language = _detect_language(user_message)
        err_msg = f"{prefix_content}❌ 任务执行时发生意外错误，请稍后重试。" if user_language == "zh" else f"{prefix_content}❌ An unexpected error occurred. Please try again."
        save_message_to_session(session_id, "assistant", err_msg)
        await socket_manager.emit("server_event", {
            "type": "task.summary",
            "payload": {"session_id": session_id, "content": err_msg},
        })
        return err_msg
    
    # 格式化结果并推送
    return await _format_and_push_result(
        run_record, decision, avatar_router, session_id, prefix_content, memory_manager,
        task_start_ms=task_start_ms,
    )


async def _emit_plan_and_steps(run_record, intent, session_id: str):
    """
    任务执行完成后，向前端补发 plan.generated + step.end 事件。
    优先从 run_record._graph（ExecutionGraph）读取节点信息，
    fallback 到 run_record.steps（DB 记录）。
    """
    plan_id = getattr(run_record, "id", str(uuid.uuid4()))
    goal = getattr(intent, "goal", "Task")

    # 优先从 ExecutionGraph 读取节点（GraphController 不写 StepStore）
    graph = getattr(run_record, "_graph", None)

    try:
        if graph and graph.nodes:
            # 从 ExecutionGraph.nodes 构建 steps_payload
            nodes = list(graph.nodes.values())
            steps_payload = []
            for i, node in enumerate(nodes):
                steps_payload.append({
                    "id": str(node.id),
                    "skill": node.capability_name,
                    "skill_name": node.capability_name,
                    "description": node.capability_name.replace(".", " → "),
                    "status": "pending",
                    "order": i,
                    "params": node.params or {},
                    "depends_on": [],
                })

            # 发 plan.generated
            await socket_manager.emit("server_event", {
                "type": "plan.generated",
                "payload": {
                    "session_id": session_id,
                    "plan": {
                        "id": plan_id,
                        "goal": goal,
                        "steps": steps_payload,
                    },
                },
            })

            # 逐节点发 step.end / step.failed
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            for node in nodes:
                is_failed = node.status == NodeStatus.FAILED
                event_type = "step.failed" if is_failed else "step.end"

                outputs = node.outputs or {}
                b64_image = None
                if isinstance(outputs, dict):
                    b64_image = outputs.get("base64_image")

                await socket_manager.emit("server_event", {
                    "type": event_type,
                    "step_id": str(node.id),
                    "payload": {
                        "session_id": session_id,
                        "skill_name": node.capability_name,
                        "status": "failed" if is_failed else "completed",
                        "raw_output": outputs,
                        "base64_image": b64_image,
                        "error": node.error_message if is_failed else None,
                    },
                })

        elif run_record.steps:
            # Fallback: 从 DB steps 读取（旧架构兼容）
            steps_payload = []
            for i, step in enumerate(run_record.steps):
                skill_name = getattr(step, "skill_name", "unknown")
                step_id = getattr(step, "id", f"step_{i}")
                input_params = getattr(step, "input_params", {}) or {}
                steps_payload.append({
                    "id": str(step_id),
                    "skill": skill_name,
                    "skill_name": skill_name,
                    "description": skill_name.replace(".", " → "),
                    "status": "pending",
                    "order": i,
                    "params": input_params,
                    "depends_on": [],
                })

            await socket_manager.emit("server_event", {
                "type": "plan.generated",
                "payload": {
                    "session_id": session_id,
                    "plan": {"id": plan_id, "goal": goal, "steps": steps_payload},
                },
            })

            for i, step in enumerate(run_record.steps):
                skill_name = getattr(step, "skill_name", "unknown")
                step_id = getattr(step, "id", f"step_{i}")
                status = getattr(step, "status", "completed")
                output_result = getattr(step, "output_result", {}) or {}
                error_message = getattr(step, "error_message", None)
                is_failed = str(status).lower() == "failed"

                b64_image = None
                if isinstance(output_result, dict):
                    val = output_result.get("value", output_result)
                    if isinstance(val, dict):
                        b64_image = val.get("base64_image")

                await socket_manager.emit("server_event", {
                    "type": "step.failed" if is_failed else "step.end",
                    "step_id": str(step_id),
                    "payload": {
                        "session_id": session_id,
                        "skill_name": skill_name,
                        "status": "failed" if is_failed else "completed",
                        "raw_output": output_result,
                        "base64_image": b64_image,
                        "error": error_message,
                    },
                })
        else:
            logger.warning(f"[_emit_plan_and_steps] No graph nodes or DB steps found for run {plan_id}")

    except Exception as e:
        logger.error(f"[_emit_plan_and_steps] Failed to emit plan/steps: {e}", exc_info=True)

    # task.completed 无论如何都要发，保证前端状态机能推进
    try:
        final_status = getattr(run_record, "status", "completed")
        step_count = len(graph.nodes) if (graph and graph.nodes) else (len(run_record.steps) if run_record.steps else 0)
        await socket_manager.emit("server_event", {
            "type": "task.completed",
            "payload": {
                "session_id": session_id,
                "task": {
                    "id": plan_id,
                    "status": "FAILED" if final_status != "completed" else "SUCCESS",
                },
                "step_count": step_count,
            },
        })
    except Exception as e:
        logger.error(f"[_emit_plan_and_steps] Failed to emit task.completed: {e}", exc_info=True)


async def _handle_planning_failure(error, avatar_router, decision, user_message, session_id, prefix_content):
    """处理任务执行失败（RuntimeError）的优雅降级，通过 Socket 推送结果"""
    from .session import save_message_to_session

    logger.warning(f"[TaskExecution] Task failed for goal='{decision.goal}': {error}")
    user_language = _detect_language(user_message)
    error_class = _classify_execution_error(error)

    if error_class == "infra":
        # 基础设施错误：LLM 无额外信息，直接给友好提示
        if user_language == "zh":
            result_msg = f"{prefix_content}⚠️ 沙箱暂时不可用，请稍后重试。"
        else:
            result_msg = f"{prefix_content}⚠️ Sandbox is temporarily unavailable. Please try again later."

    elif error_class == "code":
        # 代码错误：LLM 分析 traceback，给出修复建议
        analysis = await _analyze_code_error(
            llm_client=avatar_router.llm,
            goal=decision.goal or user_message,
            error_detail=str(error),
            user_language=user_language,
        )
        if analysis:
            if user_language == "zh":
                result_msg = f"{prefix_content}❌ 代码执行失败\n\n{analysis}"
            else:
                result_msg = f"{prefix_content}❌ Code execution failed\n\n{analysis}"
        else:
            if user_language == "zh":
                result_msg = f"{prefix_content}❌ 代码执行失败，请检查代码逻辑后重试。"
            else:
                result_msg = f"{prefix_content}❌ Code execution failed. Please check your code and retry."

    else:
        # 未知错误：简洁提示，不暴露堆栈
        if user_language == "zh":
            result_msg = f"{prefix_content}❌ 任务执行失败，请稍后重试。"
        else:
            result_msg = f"{prefix_content}❌ Task execution failed. Please try again."

    save_message_to_session(session_id, "assistant", result_msg)
    await socket_manager.emit("server_event", {
        "type": "task.summary",
        "payload": {"session_id": session_id, "content": result_msg},
    })


def _build_run_summary_payload(graph, run_record, start_time_ms: int = 0) -> dict:
    """
    从 ExecutionGraph 构建 run_summary payload，直接在后端计算，
    前端不再依赖 taskStore 运行时状态来统计步骤。
    """
    from app.avatar.runtime.graph.models.step_node import NodeStatus

    if graph and graph.nodes:
        nodes = list(graph.nodes.values())
        total = len(nodes)
        completed = sum(1 for n in nodes if n.status == NodeStatus.COMPLETED)
        failed = sum(1 for n in nodes if n.status == NodeStatus.FAILED)
        duration_ms = int((datetime.now(timezone.utc).timestamp() * 1000) - start_time_ms) if start_time_ms else 0

        key_outputs = []
        for n in nodes:
            if n.status == NodeStatus.COMPLETED and n.outputs:
                outputs = n.outputs
                summary_val = (
                    outputs.get("stdout") or outputs.get("output") or
                    outputs.get("content") or outputs.get("message")
                )
                if summary_val and isinstance(summary_val, str) and summary_val.strip():
                    key_outputs.append({
                        "skill_name": n.capability_name,
                        "step_name": n.capability_name.split(".")[-1],
                        "summary": summary_val.strip()[:120],
                    })

        return {
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "duration_ms": duration_ms,
            "key_outputs": key_outputs[-3:],  # 最多 3 个
        }

    # fallback: DB steps
    if hasattr(run_record, "steps") and run_record.steps:
        steps = run_record.steps
        total = len(steps)
        completed = sum(1 for s in steps if getattr(s, "status", "") == "completed")
        failed = sum(1 for s in steps if getattr(s, "status", "") == "failed")
        return {
            "total_steps": total,
            "completed_steps": completed,
            "failed_steps": failed,
            "duration_ms": 0,
            "key_outputs": [],
        }

    return {"total_steps": 0, "completed_steps": 0, "failed_steps": 0, "duration_ms": 0, "key_outputs": []}


async def _format_and_push_result(run_record, decision, avatar_router, session_id, prefix_content, memory_manager=None, task_start_ms: int = 0):
    """格式化任务结果并通过 Socket 推送到前端，同时保存到 session 历史"""
    from .session import save_message_to_session

    # llm.fallback 特殊处理：输出是对话消息，不是任务结果
    graph = getattr(run_record, "_graph", None)
    if graph and graph.nodes:
        nodes = list(graph.nodes.values())
        last_node = nodes[-1]
        if last_node.capability_name == "llm.fallback":
            outputs = last_node.outputs or {}
            # FallbackOutput 结构：response_zh / response_en / next_steps
            fallback_msg = (
                outputs.get("response_zh")
                or outputs.get("response_en")
                or outputs.get("message")
                or "我暂时无法完成这个请求，请补充更多信息。"
            )
            # next_steps 拼接到消息末尾
            next_steps = outputs.get("next_steps") or []
            if next_steps:
                steps_text = "\n".join(
                    f"- {s.get('zh', s.get('en', ''))}" for s in next_steps if isinstance(s, dict)
                )
                if steps_text:
                    fallback_msg = f"{fallback_msg}\n\n{steps_text}"

            chat_msg = prefix_content + fallback_msg
            # 保存为普通 chat 消息（message_type=chat），下一轮 ReferenceResolver 可正常识别
            save_message_to_session(session_id, "assistant", chat_msg)
            await socket_manager.emit("server_event", {
                "type": "task.summary",
                "payload": {"session_id": session_id, "content": chat_msg},
            })
            logger.info(f"[llm.fallback] Pushed as chat message, len={len(chat_msg)}")
            return chat_msg

    # 优先从 ExecutionGraph 读取最后一个节点的输出
    graph = getattr(run_record, "_graph", None)
    real_b64_image = None
    target_obj = None

    if graph and graph.nodes:
        nodes = list(graph.nodes.values())
        last_node = nodes[-1]
        outputs = last_node.outputs or {}
        real_b64_image = outputs.get("base64_image")
        target_obj = {k: v for k, v in outputs.items() if k != "base64_image"} or outputs
        success = True
    else:
        success, output_val, real_b64_image, target_obj = _extract_step_result(run_record)
    
    # 任务失败：从 graph nodes 取真实错误信息，按错误类型处理
    if run_record.status != "completed":
        # 收集所有失败节点的错误信息
        error_detail = ""
        if graph and graph.nodes:
            from app.avatar.runtime.graph.models.step_node import NodeStatus
            failed_nodes = [n for n in graph.nodes.values() if n.status == NodeStatus.FAILED]
            if failed_nodes:
                error_parts = []
                for n in failed_nodes:
                    if n.error_message:
                        error_parts.append(f"[{n.capability_name}] {n.error_message}")
                error_detail = "\n".join(error_parts)

        user_language = _detect_language("")  # 无 user_message，默认 zh
        error_class = _classify_execution_error(Exception(error_detail)) if error_detail else "unknown"

        if error_class == "infra":
            error_summary = f"{prefix_content}⚠️ 沙箱暂时不可用，请稍后重试。"
        elif error_class == "code" and error_detail:
            analysis = await _analyze_code_error(
                llm_client=avatar_router.llm,
                goal=decision.goal or "",
                error_detail=error_detail,
                user_language="zh",
            )
            if analysis:
                error_summary = f"{prefix_content}❌ 代码执行失败\n\n{analysis}"
            else:
                error_summary = f"{prefix_content}❌ 代码执行失败，请检查代码逻辑后重试。"
        else:
            detail_hint = f"\n\n`{error_detail[:300]}`" if error_detail else ""
            error_summary = f"{prefix_content}❌ 任务执行失败 (Status: {run_record.status})。{detail_hint}"

        save_message_to_session(session_id, "assistant", error_summary)
        await socket_manager.emit("server_event", {
            "type": "task.summary",
            "payload": {"session_id": session_id, "content": error_summary},
        })
        return error_summary

    # 生成友好总结
    from app.avatar.planner.summarizer import ResultSummarizer
    summary_lines = []

    # 从 graph nodes 或 DB steps 获取步骤信息
    graph = getattr(run_record, "_graph", None)
    if graph and graph.nodes:
        nodes = list(graph.nodes.values())
        step_count = len(nodes)
        last_node = nodes[-1]
        skill_name = last_node.capability_name
    elif run_record.steps:
        step_count = len(run_record.steps)
        last_step = run_record.steps[-1]
        skill_name = getattr(last_step, "skill_name", "unknown")
    else:
        step_count = 0
        skill_name = "unknown"

    if step_count == 1:
        if target_obj:
            try:
                friendly = ResultSummarizer.summarize(skill_name, target_obj, avatar_router.llm)
                summary_lines.append(f"✅ {friendly}")
            except Exception:
                summary_lines.append("✅ 任务执行完成")
        else:
            summary_lines.append("✅ 任务执行完成")
    elif step_count > 1:
        summary_lines.append("✅ **任务执行成功**\n")
        summary_lines.append(f"完成了 {step_count} 个步骤")
        if target_obj:
            try:
                friendly = ResultSummarizer.summarize(skill_name, target_obj, avatar_router.llm)
                summary_lines.append(f"\n📊 {friendly}")
            except Exception:
                pass
    else:
        summary_lines.append("✅ 任务执行完成")
    
    # 添加图片
    if real_b64_image:
        clean = real_b64_image.replace("\n", "").replace("\r", "")
        summary_lines.append(f"\n```image\n{clean}\n```")
    
    final_summary = prefix_content + "\n".join(summary_lines)
    
    # 保存任务结果到 session 历史（刷新页面后可见），携带结构化 metadata 供 Planner 跨轮引用
    task_result_summary = build_task_result_summary(
        run_record=run_record,
        goal=decision.goal or "",
        target_obj=target_obj,
        final_summary=final_summary,
    )
    save_message_to_session(
        session_id, "assistant", final_summary,
        metadata={
            "message_type": "task_result",
            "goal": task_result_summary["goal"],
            "status": task_result_summary["status"],
            "output_type": task_result_summary["output_type"],
            "output_path": task_result_summary["output_path"],
            "output_value": task_result_summary["output_value"],
        },
    )

    # 保存 last_output 到 SessionContext（供其他非 Planner 路径使用）
    try:
        from app.avatar.runtime.core import SessionContext
        if memory_manager:
            session_data = memory_manager.get_session_context(session_id)
            if session_data:
                session_ctx = SessionContext.from_dict(session_data)
            else:
                session_ctx = SessionContext.create(session_id=session_id)
            session_ctx.set_variable("last_output", final_summary)
            memory_manager.save_session_context(session_ctx)
    except Exception as e:
        logger.warning(f"Failed to save last_output to session: {e}")
    
    await socket_manager.emit("server_event", {
        "type": "task.summary",
        "payload": {
            "session_id": session_id,
            "content": final_summary,
            "run_summary": _build_run_summary_payload(
                getattr(run_record, "_graph", None), run_record, task_start_ms
            ),
        },
    })
    return final_summary
