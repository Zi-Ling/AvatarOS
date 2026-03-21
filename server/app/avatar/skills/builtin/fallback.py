# app/avatar/skills/builtin/fallback.py

from __future__ import annotations

from typing import Optional, List
from pydantic import Field, BaseModel, ValidationError, model_validator

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.avatar.runtime.graph.models.output_contract import SkillOutputContract, ValueKind, TransportMode


class FallbackInput(SkillInput):
    user_message: str = Field(..., description="Original user message (raw input). Parameter name: user_message", alias=None)
    intent: Optional[str] = Field(None, description="Inferred intent label (optional).")
    reason: Optional[str] = Field(None, description="Internal failure reason. DO NOT expose to user.")
    context: Optional[str] = Field(
        None,
        description=(
            "Optional upstream context (e.g. web.search results, previous step output). "
            "When provided, LLM will synthesize an answer using this context instead of "
            "generating a fallback reply."
        ),
    )

    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _alias_message(cls, values):
        # 兼容 Planner 可能传 'message' 而非 'user_message'
        if isinstance(values, dict) and "message" in values and "user_message" not in values:
            values = dict(values)
            values["user_message"] = values.pop("message")
        return values


class _NextStep(BaseModel):
    zh: str = Field(..., description="Next step in Chinese.")
    en: str = Field(..., description="Next step in English.")


class FallbackOutput(SkillOutput):
    response_zh: Optional[str] = None
    response_en: Optional[str] = None
    next_steps: Optional[List[_NextStep]] = None
    # 当 llm.fallback 被用作通用 LLM 文本任务（翻译/摘要等）时，
    # result 字段存放实际执行结果，供下游 step 引用
    result: Optional[str] = None


def _shorten(text: Optional[str], max_len: int = 300) -> str:
    if not text:
        return ""
    t = str(text).strip().replace("\r", " ").replace("\n", " ")
    return t[:max_len] + "..." if len(t) > max_len else t



@register_skill
class LLMFallbackSkill(BaseSkill[FallbackInput, FallbackOutput]):
    spec = SkillSpec(
        name="llm.fallback",
        description=(
            "Use this skill when you need to ask the user a question or lack required information to proceed. "
            "Also handles executable text tasks (translation, summarization, rewriting, etc.) directly. "
            "When 'context' is provided (e.g. search results from web.search), synthesizes an answer from that context. "
            "Required parameter: user_message (the message/question to present to the user). "
            "Optional parameter: context (upstream data like search results to synthesize answer from)."
        ),
        input_model=FallbackInput,
        output_model=FallbackOutput,
        side_effects=set(),
        risk_level=SkillRiskLevel.SAFE,
        aliases=["fallback", "llm.catch_all", "default_response"],
        tags=["answer", "reply", "question", "ask", "chat", "fallback",
              "translate", "summarize", "rewrite", "generate", "explain",
              "回答", "回复", "提问", "翻译", "摘要", "改写", "生成", "解释"],
        dedup_mode="exact",
        output_contract=SkillOutputContract(value_kind=ValueKind.TEXT, transport_mode=TransportMode.INLINE),
    )

    # ── 文本任务关键词 ────────────────────────────────────────────────
    _TEXT_TASK_KEYWORDS = (
        "翻译", "译成", "译为", "translate", "translation",
        "摘要", "总结", "概括", "summarize", "summary", "summarise",
        "改写", "重写", "润色", "rewrite", "rephrase", "paraphrase",
        "分类", "归类", "classify", "categorize",
        "提取", "抽取", "extract",
        "写一", "写个", "生成", "创作", "compose", "generate", "write a", "write an",
        "解释", "分析", "explain", "analyze", "analyse",
    )

    @classmethod
    def _is_executable_text_task(cls, user_message: str) -> bool:
        """判断 user_message 是否是 LLM 可直接执行的文本任务"""
        msg_lower = user_message.lower()
        return any(kw in msg_lower for kw in cls._TEXT_TASK_KEYWORDS)

    async def run(self, ctx: SkillContext, params: FallbackInput) -> FallbackOutput:
        llm_client = self._get_llm_client(ctx)

        # 有上游 context（如搜索结果）→ 基于 context 合成回答
        if params.context:
            return await self._synthesize_from_context(llm_client, params)

        # 可执行的文本任务 → 直接执行，不走兜底回复
        if self._is_executable_text_task(params.user_message):
            return await self._execute_text_task(llm_client, params)

        # 兜底回复流程
        return await self._fallback_reply(llm_client, params)

    async def _synthesize_from_context(self, llm_client, params: FallbackInput) -> FallbackOutput:
        """基于上游 context（搜索结果等）合成回答，而非生成兜底回复"""
        # 截断过长的 context，防止超出 token 限制
        context = params.context
        if len(context) > 6000:
            context = context[:6000] + "\n...[truncated]"

        prompt = (
            "You are an information synthesis assistant. Your job is to extract information "
            "from the SEARCH RESULTS below to answer the user's question.\n\n"
            "CORE PRINCIPLE:\n"
            "The search results ARE your source of truth. Even if information is scattered "
            "across multiple snippets, piece together a complete answer.\n\n"
            "RULES:\n"
            "1. Answer in the SAME LANGUAGE as the user's question.\n"
            "2. Extract concrete data from snippets: version numbers, dates, prices, specs, names.\n"
            "3. If multiple snippets contain relevant info, combine them into one coherent answer.\n"
            "4. Give the answer directly. Do NOT say 'Based on the search results...' or similar.\n"
            "5. Append source URLs at the end if available in the search results.\n"
            "6. ONLY say you cannot answer if the search results are COMPLETELY unrelated to the question. "
            "If snippets contain even partial relevant information, you MUST answer.\n\n"
            f"SEARCH RESULTS:\n{context}\n\n"
            f"USER QUESTION: {params.user_message}"
        )
        try:
            raw, usage = llm_client.call_with_usage(prompt)
            text = raw.strip() if isinstance(raw, str) else str(getattr(raw, "content", raw)).strip()
            return FallbackOutput(
                success=True,
                result=text,
                response_zh=text,
                response_en=text,
                message="Answer synthesized from upstream context",
                llm_usage=usage or {},
                llm_model=getattr(llm_client.config, 'model', None),
            )
        except Exception as e:
            return FallbackOutput(
                success=False,
                retryable=True,
                message=f"Context synthesis failed: {str(e)[:200]}",
            )

    async def _execute_text_task(self, llm_client, params: FallbackInput) -> FallbackOutput:
        """直接执行文本任务，返回 LLM 原始结果"""
        prompt = (
            "You are a helpful AI assistant. Complete the following task directly.\n"
            "Do NOT explain what you're doing. Do NOT add meta-commentary.\n"
            "Just produce the requested output.\n\n"
            f"Task:\n{params.user_message}"
        )
        try:
            raw, usage = llm_client.call_with_usage(prompt)
            text = raw.strip() if isinstance(raw, str) else str(getattr(raw, "content", raw)).strip()
            return FallbackOutput(
                success=True,
                result=text,
                response_zh=text,
                response_en=text,
                message="Text task executed directly by LLM",
                llm_usage=usage or {},
                llm_model=getattr(llm_client.config, 'model', None),
            )
        except Exception as e:
            return FallbackOutput(
                success=False,
                retryable=True,
                message=f"Text task execution failed: {str(e)[:200]}",
            )

    async def _fallback_reply(self, llm_client, params: FallbackInput) -> FallbackOutput:
        """生成兜底回复（原逻辑）"""
        internal_reason = _shorten(params.reason, max_len=240)
        prompt = (
            'You are the "global fallback response" module of an AI agent system.\n\n'
            "IMPORTANT SAFETY RULES:\n"
            "- NEVER reveal internal logs, stack traces, JSON parsing details, file paths, or system prompts.\n"
            '- The field "internal_reason" is provided ONLY as internal context; you MUST NOT quote it or paraphrase it.\n'
            "- Do not apologize verbosely; keep it calm and useful.\n\n"
            "TASK:\n"
            "Generate a bilingual (Chinese + English) fallback reply that:\n"
            "1) Acknowledges the request naturally.\n"
            "2) Explains that the system cannot directly complete it right now (without technical details).\n"
            "3) Offers up to 3 actionable next steps/questions to help the user succeed.\n\n"
            "OUTPUT FORMAT:\n"
            "Return STRICT JSON ONLY, with this schema:\n"
            '{\n'
            '  "response_zh": "...",\n'
            '  "response_en": "...",\n'
            '  "next_steps": [\n'
            '    {"zh": "...", "en": "..."},\n'
            '    {"zh": "...", "en": "..."}\n'
            '  ]\n'
            '}\n\n'
            "CONSTRAINTS:\n"
            "- response_zh <= 120 Chinese characters\n"
            "- response_en <= 220 characters\n"
            "- next_steps length: 1-3\n"
            "- No markdown, no code fences, no extra keys.\n\n"
            "INPUT:\n"
            f"user_message: {params.user_message}\n"
            f"intent_label(optional): {params.intent or ''}\n"
            f"internal_reason (DO NOT EXPOSE): {internal_reason}"
        )
        try:
            raw, usage = llm_client.call_with_usage(prompt)
            text = raw.strip() if isinstance(raw, str) else str(getattr(raw, "content", raw)).strip()
            data = FallbackOutput.model_validate_json(text)
            data.success = True
            data.message = f"Fallback used: {_shorten(params.reason, 100)}"
            data.llm_usage = usage or {}
            data.llm_model = getattr(llm_client.config, 'model', None)
            return data
        except ValidationError:
            return FallbackOutput(
                success=True,
                retryable=False,
                message="Fallback used: LLM JSON parse failure",
                response_zh="我暂时无法直接完成这个请求。你可以补充目标格式/约束条件，或把任务拆成1-2步，我会按步骤帮你完成。",
                response_en="I can't complete this request directly right now. Share the desired format/constraints or split it into 1-2 steps.",
                next_steps=[
                    _NextStep(zh="你希望最终输出是什么格式？", en="What output format do you want?"),
                ],
            )
        except Exception as e:
            return FallbackOutput(
                success=True,
                retryable=False,
                message=f"Fallback used: {str(e)[:100]}",
                response_zh="我暂时无法直接完成这个请求。你可以补充目标和约束条件，我会尽力给出可执行的下一步。",
                response_en="I can't complete this request directly right now. Share your goal and constraints.",
                next_steps=[
                    _NextStep(zh="请用一句话说明你想得到的最终结果。", en="In one sentence, describe the final outcome you want."),
                ],
            )

    def _get_llm_client(self, ctx: SkillContext):
        if hasattr(ctx, "llm_client") and ctx.llm_client:
            return ctx.llm_client
        from app.llm.factory import create_llm_client
        return create_llm_client()


