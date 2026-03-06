# server/app/avatar/skills/core/memory.py

from __future__ import annotations

import logging
from typing import Optional, Any, List, Dict
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext
from app.services.memory_service import get_memory_service

logger = logging.getLogger(__name__)


# ============================================================================
# memory.store - 存储长期记忆
# ============================================================================

class MemoryStoreInput(SkillInput):
    content: str = Field(..., description="Memory content to store")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata for filtering (e.g., category, tags)")
    memory_id: Optional[str] = Field(None, description="Optional memory ID (auto-generated if not provided)")

class MemoryStoreOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: memory ID")
    memory_id: str

@register_skill
class MemoryStoreSkill(BaseSkill[MemoryStoreInput, MemoryStoreOutput]):
    spec = SkillSpec(
        name="memory.store",
        api_name="memory.store",
        aliases=["store_memory", "save_memory"],
        description="Store long-term memory using vector database. 存储长期记忆到向量库。",
        category=SkillCategory.SYSTEM,
        input_model=MemoryStoreInput,
        output_model=MemoryStoreOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.WRITE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["save memory", "remember", "store knowledge", "保存记忆", "存储知识"],
        
        examples=[
            {"description": "Store user preference", "params": {"content": "User prefers dark mode", "metadata": {"category": "preference"}}},
            {"description": "Store knowledge", "params": {"content": "Python uses snake_case for variables", "metadata": {"category": "knowledge", "language": "python"}}},
        ],
        
        permissions=[SkillPermission(name="memory_write", description="Write memory")],
        tags=["memory", "storage", "vector", "记忆", "存储"]
    )

    async def run(self, ctx: SkillContext, params: MemoryStoreInput) -> MemoryStoreOutput:
        if ctx.dry_run:
            return MemoryStoreOutput(
                success=True,
                message=f"[dry_run] Would store memory: {params.content[:50]}...",
                memory_id="dry_run_id",
                output="dry_run_id"
            )

        try:
            service = get_memory_service()
            memory_id = service.store(
                content=params.content,
                metadata=params.metadata,
                memory_id=params.memory_id
            )
            
            return MemoryStoreOutput(
                success=True,
                message=f"Memory stored: {memory_id}",
                memory_id=memory_id,
                output=memory_id
            )
        
        except Exception as e:
            return MemoryStoreOutput(
                success=False,
                message=str(e),
                memory_id="",
                output=None
            )


# ============================================================================
# memory.search - 搜索长期记忆
# ============================================================================

class MemorySearchInput(SkillInput):
    query: str = Field(..., description="Search query text")
    limit: int = Field(5, description="Maximum number of results")
    filter_metadata: Optional[Dict[str, Any]] = Field(None, description="Metadata filter (e.g., {'category': 'preference'})")

class MemorySearchOutput(SkillOutput):
    output: Optional[List[Dict[str, Any]]] = Field(None, description="Primary output: search results")
    results: List[Dict[str, Any]] = []
    count: int = 0

@register_skill
class MemorySearchSkill(BaseSkill[MemorySearchInput, MemorySearchOutput]):
    spec = SkillSpec(
        name="memory.search",
        api_name="memory.search",
        aliases=["search_memory", "recall_memory"],
        description="Search long-term memory using semantic similarity. 使用语义相似度搜索长期记忆。",
        category=SkillCategory.SYSTEM,
        input_model=MemorySearchInput,
        output_model=MemorySearchOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.READ},
            risk_level=SkillRiskLevel.READ,
            priority=10,
        ),
        
        synonyms=["recall", "find memory", "search knowledge", "搜索记忆", "查找知识"],
        
        examples=[
            {"description": "Search preferences", "params": {"query": "user interface preferences", "limit": 3}},
            {"description": "Search with filter", "params": {"query": "python coding style", "filter_metadata": {"category": "knowledge"}}},
        ],
        
        permissions=[SkillPermission(name="memory_read", description="Read memory")],
        tags=["memory", "search", "vector", "记忆", "搜索"]
    )

    async def run(self, ctx: SkillContext, params: MemorySearchInput) -> MemorySearchOutput:
        if ctx.dry_run:
            return MemorySearchOutput(
                success=True,
                message=f"[dry_run] Would search memory: {params.query}",
                results=[],
                count=0,
                output=[]
            )

        try:
            service = get_memory_service()
            results = service.search(
                query=params.query,
                limit=params.limit,
                filter_metadata=params.filter_metadata
            )
            
            return MemorySearchOutput(
                success=True,
                message=f"Found {len(results)} memories",
                results=results,
                count=len(results),
                output=results
            )
        
        except Exception as e:
            return MemorySearchOutput(
                success=False,
                message=str(e),
                results=[],
                count=0,
                output=[]
            )


# ============================================================================
# memory.delete - 删除长期记忆
# ============================================================================

class MemoryDeleteInput(SkillInput):
    memory_id: str = Field(..., description="Memory ID to delete")

class MemoryDeleteOutput(SkillOutput):
    output: Optional[str] = Field(None, description="Primary output: deleted memory ID")
    memory_id: str

@register_skill
class MemoryDeleteSkill(BaseSkill[MemoryDeleteInput, MemoryDeleteOutput]):
    spec = SkillSpec(
        name="memory.delete",
        api_name="memory.delete",
        aliases=["delete_memory", "forget"],
        description="Delete long-term memory. 删除长期记忆。",
        category=SkillCategory.SYSTEM,
        input_model=MemoryDeleteInput,
        output_model=MemoryDeleteOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.SYSTEM,
            capabilities={SkillCapability.DELETE},
            risk_level=SkillRiskLevel.WRITE,
            priority=10,
        ),
        
        synonyms=["forget", "remove memory", "删除记忆", "遗忘"],
        
        examples=[
            {"description": "Delete memory", "params": {"memory_id": "mem_20250101_120000_123456"}},
        ],
        
        permissions=[SkillPermission(name="memory_write", description="Delete memory")],
        tags=["memory", "delete", "记忆", "删除"]
    )

    async def run(self, ctx: SkillContext, params: MemoryDeleteInput) -> MemoryDeleteOutput:
        if ctx.dry_run:
            return MemoryDeleteOutput(
                success=True,
                message=f"[dry_run] Would delete memory: {params.memory_id}",
                memory_id=params.memory_id,
                output=params.memory_id
            )

        try:
            service = get_memory_service()
            success = service.delete(params.memory_id)
            
            if not success:
                return MemoryDeleteOutput(
                    success=False,
                    message="Failed to delete memory",
                    memory_id=params.memory_id,
                    output=None
                )
            
            return MemoryDeleteOutput(
                success=True,
                message=f"Memory deleted: {params.memory_id}",
                memory_id=params.memory_id,
                output=params.memory_id
            )
        
        except Exception as e:
            return MemoryDeleteOutput(
                success=False,
                message=str(e),
                memory_id=params.memory_id,
                output=None
            )
