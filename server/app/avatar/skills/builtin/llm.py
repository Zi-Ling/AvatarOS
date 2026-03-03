# app/avatar/skills/builtin/llm.py

from __future__ import annotations

from typing import Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# llm.generate_text
# ============================================================================

class GenerateTextInput(SkillInput):
    prompt: str = Field(..., description="The prompt or instruction for text generation.")
    max_length: Optional[int] = Field(None, description="Maximum length of generated text (in characters).")
    temperature: Optional[float] = Field(None, description="Temperature for generation (0.0-1.0). Higher = more creative.")

class GenerateTextOutput(SkillOutput):
    text: Optional[str] = None
    tokens_used: Optional[int] = None

@register_skill
class LLMGenerateTextSkill(BaseSkill[GenerateTextInput, GenerateTextOutput]):
    spec = SkillSpec(
        name="llm.generate_text",
        api_name="llm.generate_text",
        aliases=["llm.generate", "llm.create", "text.generate"],
        description="Generate creative text content using LLM (poems, stories, essays, etc.). 使用LLM生成创意文本（诗歌、故事、文章等）。",
        category=SkillCategory.OTHER,
        input_model=GenerateTextInput,
        output_model=GenerateTextOutput,
        
        # Capability Routing Metadata
        meta=SkillMetadata(
            domain=SkillDomain.OTHER,
            capabilities={SkillCapability.CREATE},
            risk_level="low"
        ),
        
        synonyms=[
            "generate text",
            "create content",
            "write poem",
            "write story",
            "compose text",
            "生成文本",
            "创作内容",
            "写诗",
            "写故事",
            "生成内容"
        ],
        examples=[
            {"description": "Generate a poem about spring", "params": {"prompt": "Write a short poem about spring"}},
            {"description": "Create a product description", "params": {"prompt": "Write a product description for a wireless mouse"}}
        ],
        tags=["llm", "text", "generation", "creative", "文本生成", "创作"]
    )

    async def run(self, ctx: SkillContext, params: GenerateTextInput) -> GenerateTextOutput:
        try:
            import asyncio
            # Get LLM client from context
            llm_client = self._get_llm_client(ctx)
            
            # Build prompt
            prompt = params.prompt
            
            # Add length constraint if specified
            if params.max_length:
                prompt += f"\n\n(Keep the response under {params.max_length} characters)"
            
            # Call LLM (via thread to avoid blocking event loop)
            response = await asyncio.to_thread(llm_client.call, prompt)
            
            # Extract text (handle both string and structured response)
            if isinstance(response, str):
                generated_text = response
            elif hasattr(response, 'content'):
                generated_text = response.content
            else:
                generated_text = str(response)
            
            # Trim if needed
            if params.max_length and len(generated_text) > params.max_length:
                generated_text = generated_text[:params.max_length] + "..."
            
            return GenerateTextOutput(
                success=True,
                message="Text generated successfully",
                text=generated_text,
                tokens_used=len(generated_text) // 4  # Rough estimate
            )
            
        except Exception as e:
            return GenerateTextOutput(
                success=False,
                message=f"Failed to generate text: {str(e)}",
                text=None
            )
    
    def _get_llm_client(self, ctx: SkillContext):
        """Get LLM client from context or create default one"""
        # Try to get from context
        if hasattr(ctx, 'llm_client') and ctx.llm_client:
            return ctx.llm_client
        
        # Fallback: create default LLM client
        try:
            from app.llm.factory import create_llm_client
            return create_llm_client()
        except Exception as e:
            raise RuntimeError(f"Failed to get LLM client: {e}")


# ============================================================================
# llm.summarize
# ============================================================================

class SummarizeInput(SkillInput):
    text: str = Field(..., description="The text to summarize.")
    max_length: Optional[int] = Field(200, description="Maximum length of summary (in characters).")
    style: Optional[str] = Field("concise", description="Summary style: 'concise', 'detailed', or 'bullet_points'.")

class SummarizeOutput(SkillOutput):
    summary: Optional[str] = None
    original_length: Optional[int] = None
    summary_length: Optional[int] = None

@register_skill
class LLMSummarizeSkill(BaseSkill[SummarizeInput, SummarizeOutput]):
    spec = SkillSpec(
        name="llm.summarize",
        api_name="llm.summarize",
        aliases=["text.summarize", "summarize"],
        description="Summarize long text into a shorter version. 总结长文本为简短版本。",
        category=SkillCategory.OTHER,
        input_model=SummarizeInput,
        output_model=SummarizeOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.OTHER,
            capabilities={SkillCapability.READ},
            risk_level="low"
        ),
        
        synonyms=[
            "summarize text",
            "shorten text",
            "condense",
            "make summary",
            "总结",
            "摘要",
            "概括",
            "缩短文本"
        ],
        examples=[
            {"description": "Summarize a long article", "params": {"text": "Long article content...", "max_length": 200}}
        ],
        tags=["llm", "text", "summary", "condensing", "总结", "摘要"]
    )

    async def run(self, ctx: SkillContext, params: SummarizeInput) -> SummarizeOutput:
        try:
            import asyncio
            llm_client = self._get_llm_client(ctx)
            
            # Build prompt based on style
            if params.style == "bullet_points":
                style_instruction = "Provide a summary in bullet points."
            elif params.style == "detailed":
                style_instruction = "Provide a detailed summary covering main points."
            else:
                style_instruction = "Provide a concise summary."
            
            prompt = f"""Summarize the following text.

{style_instruction}
Keep the summary under {params.max_length} characters.

Text to summarize:
{params.text}

Summary:"""
            
            response = await asyncio.to_thread(llm_client.call, prompt)
            
            # Extract summary
            if isinstance(response, str):
                summary = response.strip()
            elif hasattr(response, 'content'):
                summary = response.content.strip()
            else:
                summary = str(response).strip()
            
            # Trim if needed
            if len(summary) > params.max_length:
                summary = summary[:params.max_length] + "..."
            
            return SummarizeOutput(
                success=True,
                message="Text summarized successfully",
                summary=summary,
                original_length=len(params.text),
                summary_length=len(summary)
            )
            
        except Exception as e:
            return SummarizeOutput(
                success=False,
                message=f"Failed to summarize: {str(e)}",
                summary=None
            )
    
    def _get_llm_client(self, ctx: SkillContext):
        """Get LLM client from context or create default one"""
        if hasattr(ctx, 'llm_client') and ctx.llm_client:
            return ctx.llm_client
        
        try:
            from app.llm.factory import create_llm_client
            return create_llm_client()
        except Exception as e:
            raise RuntimeError(f"Failed to get LLM client: {e}")


# ============================================================================
# llm.answer_question
# ============================================================================

class AnswerQuestionInput(SkillInput):
    question: str = Field(..., description="The question to answer.")
    context: Optional[str] = Field(None, description="Optional context or background information.")
    max_length: Optional[int] = Field(500, description="Maximum length of answer (in characters).")

class AnswerQuestionOutput(SkillOutput):
    answer: Optional[str] = None
    confidence: Optional[str] = None  # "high", "medium", "low"

@register_skill
class LLMAnswerQuestionSkill(BaseSkill[AnswerQuestionInput, AnswerQuestionOutput]):
    spec = SkillSpec(
        name="llm.answer_question",
        api_name="llm.answer_question",
        aliases=["llm.answer", "llm.qa", "question.answer"],
        description="Answer a question, optionally using provided context. 回答问题，可选择使用提供的上下文。",
        category=SkillCategory.OTHER,
        input_model=AnswerQuestionInput,
        output_model=AnswerQuestionOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.OTHER,
            capabilities={SkillCapability.READ},
            risk_level="low"
        ),
        
        synonyms=[
            "answer question",
            "respond to query",
            "provide answer",
            "回答问题",
            "解答",
            "答复"
        ],
        examples=[
            {"description": "Answer a factual question", "params": {"question": "What is the capital of France?"}},
            {"description": "Answer with context", "params": {"question": "What's the main topic?", "context": "Document text..."}}
        ],
        tags=["llm", "question", "answer", "qa", "问答", "回答"]
    )

    async def run(self, ctx: SkillContext, params: AnswerQuestionInput) -> AnswerQuestionOutput:
        try:
            import asyncio
            llm_client = self._get_llm_client(ctx)
            
            # Build prompt
            if params.context:
                prompt = f"""Answer the following question based on the provided context.

Context:
{params.context}

Question: {params.question}

Answer (keep under {params.max_length} characters):"""
            else:
                prompt = f"""Answer the following question concisely.

Question: {params.question}

Answer (keep under {params.max_length} characters):"""
            
            response = await asyncio.to_thread(llm_client.call, prompt)
            
            # Extract answer
            if isinstance(response, str):
                answer = response.strip()
            elif hasattr(response, 'content'):
                answer = response.content.strip()
            else:
                answer = str(response).strip()
            
            # Trim if needed
            if len(answer) > params.max_length:
                answer = answer[:params.max_length] + "..."
            
            # Simple confidence heuristic
            confidence = "high" if len(answer) > 20 else "low"
            
            return AnswerQuestionOutput(
                success=True,
                message="Question answered successfully",
                answer=answer,
                confidence=confidence
            )
            
        except Exception as e:
            return AnswerQuestionOutput(
                success=False,
                message=f"Failed to answer question: {str(e)}",
                answer=None
            )
    
    def _get_llm_client(self, ctx: SkillContext):
        """Get LLM client from context or create default one"""
        if hasattr(ctx, 'llm_client') and ctx.llm_client:
            return ctx.llm_client
        
        try:
            from app.llm.factory import create_llm_client
            return create_llm_client()
        except Exception as e:
            raise RuntimeError(f"Failed to get LLM client: {e}")

