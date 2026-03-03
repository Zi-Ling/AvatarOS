# app/api/knowledge.py
"""
Knowledge Base API

提供 Memory、Habits、Skills 统计等数据的查询接口
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import logging

from app.avatar.memory.manager import MemoryManager
from app.avatar.memory.provider import get_memory_manager
from app.avatar.learning.manager import LearningManager
from app.avatar.learning.provider import get_learning_manager

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

logger = logging.getLogger(__name__)


# ============================================================================
# Response Models
# ============================================================================

class MemoryItemResponse(BaseModel):
    """记忆项"""
    id: str
    content: str
    category: str  # 'task', 'skill', 'user_pref'
    created_at: str
    confidence: float = 1.0


class HabitItemResponse(BaseModel):
    """习惯项（用户偏好）"""
    id: str
    description: str
    trigger_count: int
    is_active: bool
    detected_at: str


class SkillStatsResponse(BaseModel):
    """技能统计"""
    skill_name: str
    total_uses: int
    success_count: int
    failed_count: int
    success_rate: float
    last_error: str | None = None


class KnowledgeSummaryResponse(BaseModel):
    """知识库概览"""
    total_memories: int
    total_habits: int
    total_skills: int
    episodic_count: int
    knowledge_count: int


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/summary", response_model=KnowledgeSummaryResponse)
async def get_knowledge_summary(
    memory_manager: MemoryManager = Depends(get_memory_manager),
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """获取知识库概览"""
    
    # 统计 Episodic Memory
    episodic_records = memory_manager.query_task_episodes(task_id="", limit=1000)
    
    # 统计 Knowledge Memory
    knowledge_records = memory_manager.query_knowledge(prefix="", limit=1000)
    
    # 统计用户偏好
    user_prefs = memory_manager.get_user_preference("default") or {}
    
    # 统计技能
    skill_stats_count = 0
    try:
        for module in learning_manager._modules:
            if module.name == "skill_stats":
                skill_stats_count = len(module.stats_snapshot)
                break
    except Exception:
        pass
    
    return KnowledgeSummaryResponse(
        total_memories=len(episodic_records),
        total_habits=len(user_prefs),
        total_skills=skill_stats_count,
        episodic_count=len(episodic_records),
        knowledge_count=len(knowledge_records),
    )


@router.get("/memories", response_model=List[MemoryItemResponse])
async def list_memories(
    limit: int = 50,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """
    获取记忆列表（Episodic Memory）
    
    返回最近的任务执行记录
    """
    records = memory_manager.query_task_episodes(task_id="", limit=limit)
    
    memories = []
    for rec in records:
        data = rec.data
        
        # 提取内容
        content = data.get("summary", "")
        if not content:
            # 尝试从 extra 中提取用户请求
            extra = data.get("extra", {})
            content = extra.get("user_request", "Unknown task")
        
        # 确定类别
        category = "task"
        if rec.key.startswith("skill:"):
            category = "skill"
        
        memories.append(MemoryItemResponse(
            id=rec.key,
            content=content[:200],  # 限制长度
            category=category,
            created_at=rec.created_at.strftime("%Y-%m-%d %H:%M"),
            confidence=1.0 if data.get("status") == "success" else 0.5,
        ))
    
    return memories


@router.get("/habits", response_model=List[HabitItemResponse])
async def list_habits(
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """
    获取用户习惯列表（User Preferences）
    
    完全重构：从 Learning 获取用户偏好，而不是直接从 Memory
    """
    user_prefs = learning_manager.get_user_preferences("default") or {}
    
    habits = []
    
    # 文件格式偏好
    if "preferred_file_format" in user_prefs:
        fmt = user_prefs["preferred_file_format"]
        habits.append(HabitItemResponse(
            id="pref_file_format",
            description=f"处理数据时优先使用 {fmt.upper()} 格式",
            trigger_count=user_prefs.get("python_usage_count", 1),
            is_active=True,
            detected_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))
    
    # 文档格式偏好
    if "preferred_doc_format" in user_prefs:
        doc_fmt = user_prefs["preferred_doc_format"]
        habits.append(HabitItemResponse(
            id="pref_doc_format",
            description=f"生成文档时优先使用 {doc_fmt.upper()} 格式",
            trigger_count=1,
            is_active=True,
            detected_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))
    
    # 用户级别（高级用户）
    if user_prefs.get("user_level") == "advanced":
        habits.append(HabitItemResponse(
            id="pref_advanced_user",
            description="遇到复杂任务时，自动使用 python.run 合并多个步骤",
            trigger_count=user_prefs.get("python_usage_count", 5),
            is_active=True,
            detected_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))
    
    # 语言偏好
    if "preferred_language" in user_prefs:
        lang = user_prefs["preferred_language"]
        lang_name = "中文" if lang == "zh" else "English"
        habits.append(HabitItemResponse(
            id="pref_language",
            description=f"生成内容时优先使用 {lang_name}",
            trigger_count=1,
            is_active=True,
            detected_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))
    
    # 如果没有任何偏好，返回空列表
    if not habits:
        habits.append(HabitItemResponse(
            id="placeholder",
            description="暂无学习到的习惯，继续使用系统来积累数据",
            trigger_count=0,
            is_active=False,
            detected_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))
    
    return habits


@router.post("/habits/{habit_id}/toggle")
async def toggle_habit(
    habit_id: str,
    is_active: bool,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """
    切换习惯的启用状态
    
    注意：这个功能暂时只是前端展示，后端还需要实现真正的"禁用偏好"逻辑
    """
    # TODO: 实现真正的禁用逻辑
    # 可以在 user_prefs 中添加一个 "disabled_prefs" 列表
    return {"success": True, "habit_id": habit_id, "is_active": is_active}


@router.get("/skills/stats", response_model=List[SkillStatsResponse])
async def get_skill_stats(
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """
    获取技能统计数据
    
    完全重构：使用 Learning 的对外接口，不直接访问内部模块
    """
    stats_list = []
    
    try:
        # 使用 Learning 的对外接口
        all_stats = learning_manager.get_skill_statistics()
        
        for skill_name, stat in all_stats.items():
            stats_list.append(SkillStatsResponse(
                skill_name=skill_name,
                total_uses=stat["total"],
                success_count=stat["success"],
                failed_count=stat["failed"],
                success_rate=stat["success_rate"],
                last_error=stat.get("last_error"),
            ))
    except Exception as e:
        logger.error(f"Failed to get skill stats: {e}")
    
    # 按使用次数排序
    stats_list.sort(key=lambda x: x.total_uses, reverse=True)
    
    return stats_list


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """
    删除指定记忆
    
    注意：这个功能需要在 MemoryManager 中实现真正的删除逻辑
    """
    # TODO: 实现真正的删除逻辑
    # 目前 JSONL 格式不支持删除，需要重写整个文件
    return {"success": True, "memory_id": memory_id}


@router.post("/cleanup")
async def trigger_cleanup(
    days_to_keep: int = 30,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """
    手动触发记忆清理
    
    删除超过 N 天的旧记录
    """
    try:
        stats = memory_manager.cleanup_old_memories(
            days_to_keep=days_to_keep,
            keep_successful_tasks=True,
        )
        return {
            "success": True,
            "deleted_count": stats.get("episodic_deleted", 0),
            "message": f"Cleaned up {stats.get('episodic_deleted', 0)} old records",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Document Upload & Indexing (轻量级实现)
# ============================================================================

# ============================================================================
# 旧的文档 API（已废弃，使用下面的新 API）
# ============================================================================
# 旧代码已删除，现在使用 Learning Manager 的 Document KB


# ============================================================================
# Document Knowledge Base API（完全重构新增）
# ============================================================================

class DocumentUploadRequest(BaseModel):
    """上传文档请求"""
    name: str
    content: str
    doc_type: str = "txt"  # txt, md


class DocumentResponse(BaseModel):
    """文档响应"""
    id: str
    name: str
    type: str
    chunks: int
    created_at: str


class DocumentSearchRequest(BaseModel):
    """文档搜索请求"""
    query: str
    max_results: int = 5


class DocumentSearchResult(BaseModel):
    """文档搜索结果"""
    chunk_id: str
    content: str
    doc_name: str
    distance: float | None = None


@router.post("/documents/upload")
async def upload_document(
    request: DocumentUploadRequest,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """
    上传文档到知识库
    
    支持的文档类型：
    - txt: 纯文本
    - md: Markdown
    
    未来可扩展：
    - pdf: PDF 文档
    - docx: Word 文档
    """
    logger.debug(f"upload_document: name={request.name}, type={request.doc_type}, len={len(request.content)}")
    
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    
    try:
        from app.avatar.learning.knowledge.document_kb import Document
        
        # 创建文档对象
        doc = Document(
            name=request.name,
            content=request.content,
            doc_type=request.doc_type,
        )
        
        # 添加到知识库
        result = learning_manager.document_kb.add_document(doc)
        logger.info(f"Document '{request.name}' uploaded: {result['chunks_count']} chunks")
        
        return {
            "success": True,
            "doc_id": result["doc_id"],
            "chunks_count": result["chunks_count"],
            "message": f"Document '{request.name}' uploaded successfully"
        }
    
    except Exception as e:
        logger.error(f"Document upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {e}")


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """列出所有文档"""
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    
    try:
        docs = learning_manager.document_kb.list_documents()
        
        return [
            DocumentResponse(
                id=doc["id"],
                name=doc["name"],
                type=doc["type"],
                chunks=doc["chunks"],
                created_at=doc["created_at"],
            )
            for doc in docs
        ]
        return result
    
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {e}")


@router.post("/documents/search", response_model=List[DocumentSearchResult])
async def search_documents(
    request: DocumentSearchRequest,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """语义搜索文档"""
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    
    try:
        matches = learning_manager.document_kb.search(
            query=request.query,
            n_results=request.max_results,
        )
        
        return [
            DocumentSearchResult(
                chunk_id=match["chunk_id"],
                content=match["content"],
                doc_name=match["metadata"].get("doc_name", "Unknown"),
                distance=match.get("distance"),
            )
            for match in matches
        ]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search documents: {e}")


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """删除文档"""
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    
    try:
        deleted_count = learning_manager.document_kb.delete_document(doc_id)
        
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
        
        return {
            "success": True,
            "deleted_chunks": deleted_count,
            "message": f"Document '{doc_id}' deleted successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {e}")


@router.get("/documents/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """获取文档完整内容"""
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    
    try:
        content = learning_manager.document_kb.get_document_content(doc_id)
        
        if content is None:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
        
        return {
            "doc_id": doc_id,
            "content": content
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get document content: {e}")

