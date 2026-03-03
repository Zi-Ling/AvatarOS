# app/api/chat/task_executor.py
"""
任务执行逻辑：后台任务执行、结果格式化、Socket 推送
"""
import inspect
import json
import logging
import uuid

from app.avatar.intent.models import IntentSpec, IntentDomain
from app.avatar.memory.manager import MemoryManager
from app.intent_router.param_extractor import ParameterExtractor
from app.io.manager import SocketManager

logger = logging.getLogger(__name__)
socket_manager = SocketManager.get_instance()


def _detect_language(text: str) -> str:
    """检测用户语言（简单启发式）"""
    return "zh" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en"


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

        # 注册取消事件
        cancellation_mgr = get_cancellation_manager()
        task_cancel_event = cancellation_mgr.register_task(initial_intent.id, session_id)
        logger.info(f"[TaskExecution] 已注册任务: {initial_intent.id}")

        run_record = await runtime.run_intent(
            initial_intent, task_mode=decision.task_mode, cancel_event=task_cancel_event,
        )
    
    except RuntimeError as e:
        return await _handle_planning_failure(
            e, avatar_router, decision, user_message, session_id, prefix_content,
        )
    
    # 格式化结果并推送
    return await _format_and_push_result(
        run_record, decision, avatar_router, session_id, prefix_content, memory_manager,
    )


async def _handle_planning_failure(error, avatar_router, decision, user_message, session_id, prefix_content):
    """处理 Planner 失败的优雅降级，通过 Socket 推送结果"""
    from .session import save_message_to_session
    
    error_msg = str(error)
    planning_keywords = ["计划不能为空", "生成执行计划时遇到了问题", "AI 理解了你的需求，但在生成执行计划时遇到了问题"]
    
    if not any(kw in error_msg for kw in planning_keywords):
        raise error
    
    logger.warning(f"[TaskExecution] Planner failed for goal='{decision.goal}', triggering fallback")
    user_language = _detect_language(user_message)
    
    result_msg = None
    try:
        if decision.relevance_score == 0.0:
            from app.avatar.skills.registry import skill_registry
            scored_skills = skill_registry.search_skills_with_scores(decision.goal, limit=5)
            if scored_skills:
                decision.relevance_score = scored_skills[0]['score']
                decision.top_skills = [s['name'] for s in scored_skills[:3]]
        
        explanation = await generate_capability_explanation(
            llm_client=avatar_router.llm,
            goal=decision.goal or user_message,
            top_skills=decision.top_skills or [],
            relevance_score=decision.relevance_score,
            user_language=user_language,
        )
        result_msg = f"{prefix_content}💡 {explanation}"
    except Exception:
        if user_language == "zh":
            result_msg = f"{prefix_content}❌ 抱歉，我理解你的需求，但暂时无法生成执行计划。建议尝试其他任务或换个方式描述。"
        else:
            result_msg = f"{prefix_content}❌ Sorry, I understand your request but cannot generate an execution plan."
    
    save_message_to_session(session_id, "assistant", result_msg)
    await socket_manager.emit("server_event", {
        "type": "task.summary",
        "payload": {"session_id": session_id, "content": result_msg},
    })


async def _format_and_push_result(run_record, decision, avatar_router, session_id, prefix_content, memory_manager=None):
    """格式化任务结果并通过 Socket 推送到前端，同时保存到 session 历史"""
    from .session import save_message_to_session
    
    success, output_val, real_b64_image, target_obj = _extract_step_result(run_record)
    
    # 任务失败
    if run_record.status != "completed":
        error_summary = (
            f"{prefix_content}⚠️ {decision.llm_explanation}\n\n"
            f"任务执行中断 (Status: {run_record.status})。"
        )
        save_message_to_session(session_id, "assistant", error_summary)
        await socket_manager.emit("server_event", {
            "type": "task.summary",
            "payload": {"session_id": session_id, "content": error_summary},
        })
        return error_summary

    # 生成友好总结
    from app.avatar.planner.summarizer import ResultSummarizer
    summary_lines = []
    
    if run_record.steps and len(run_record.steps) == 1:
        step = run_record.steps[0]
        skill_name = step.skill_name if hasattr(step, 'skill_name') else step.get('skill_name', 'unknown')
        if target_obj:
            try:
                friendly = ResultSummarizer.summarize(skill_name, target_obj, avatar_router.llm)
                summary_lines.append(f"✅ {friendly}")
            except Exception:
                summary_lines.append("✅ 任务执行完成")
        else:
            summary_lines.append("✅ 任务执行完成")
    
    elif run_record.steps and len(run_record.steps) > 1:
        summary_lines.append("✅ **任务执行成功**\n")
        summary_lines.append(f"完成了 {len(run_record.steps)} 个步骤")
        if target_obj:
            last_step = run_record.steps[-1]
            skill_name = last_step.skill_name if hasattr(last_step, 'skill_name') else last_step.get('skill_name', 'unknown')
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
    
    # 保存任务结果到 session 历史（刷新页面后可见）
    save_message_to_session(session_id, "assistant", final_summary)
    
    # 结构化产出物存入 SessionContext（供下一个任务引用）
    try:
        from app.avatar.runtime.core import SessionContext
        if memory_manager:
            session_data = memory_manager.get_session_context(session_id)
            if session_data:
                session_ctx = SessionContext.from_dict(session_data)
            else:
                session_ctx = SessionContext.create(session_id=session_id)
            
            # 存储结构化的最后任务结果
            task_result = {
                "status": run_record.status,
                "goal": decision.goal,
                "step_count": len(run_record.steps) if run_record.steps else 0,
            }
            
            # 提取产出物路径（文件类 skill 的输出）
            if target_obj and isinstance(target_obj, dict):
                for path_key in ("path", "output_path", "file_path", "current_url", "url"):
                    if path_key in target_obj and target_obj[path_key]:
                        task_result["output_path"] = str(target_obj[path_key])
                        break
            
            session_ctx.set_variable("last_task_result", task_result)
            session_ctx.set_variable("last_output", final_summary)
            memory_manager.save_session_context(session_ctx)
    except Exception as e:
        logger.warning(f"Failed to save structured task result to session: {e}")
    
    await socket_manager.emit("server_event", {
        "type": "task.summary",
        "payload": {"session_id": session_id, "content": final_summary},
    })
    return final_summary
