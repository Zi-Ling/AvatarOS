# app/api/knowledge.py
"""
Knowledge Base API
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

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

class DocumentResponse(BaseModel):
    id: str
    name: str
    type: str
    chunks: int
    created_at: str


class DocumentUploadRequest(BaseModel):
    name: str
    content: str
    doc_type: str = "txt"


class DocumentSearchRequest(BaseModel):
    query: str
    max_results: int = 5


class DocumentSearchResult(BaseModel):
    chunk_id: str
    content: str
    doc_name: str
    distance: Optional[float] = None


class KnowledgeStatusResponse(BaseModel):
    document_kb_available: bool
    vector_store_available: bool
    episodic_count: int
    knowledge_count: int


class UserPrefItem(BaseModel):
    key: str
    value: str
    updated_at: str


class EpisodicItem(BaseModel):
    id: str
    summary: str
    status: str   # success / failed
    created_at: str


class MemoriesResponse(BaseModel):
    user_prefs: List[UserPrefItem]
    episodic: List[EpisodicItem]


class MemorySearchRequest(BaseModel):
    query: str
    n_results: int = 5


class MemorySearchResult(BaseModel):
    id: str
    summary: str
    status: str
    created_at: str
    distance: Optional[float] = None


class SkillItem(BaseModel):
    name: str
    description: str
    category: str
    example_prompt: str
    aliases: List[str] = []


class McpTool(BaseModel):
    name: str
    description: str
    server: str


# ============================================================================
# Status
# ============================================================================

@router.get("/status", response_model=KnowledgeStatusResponse)
async def get_knowledge_status(
    memory_manager: MemoryManager = Depends(get_memory_manager),
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    episodic_records = memory_manager.query_task_episodes(task_id="", limit=1000)
    knowledge_records = memory_manager.query_knowledge(prefix="", limit=1000)
    return KnowledgeStatusResponse(
        document_kb_available=learning_manager.has_document_kb(),
        vector_store_available=memory_manager._vector_store is not None,
        episodic_count=len(episodic_records),
        knowledge_count=len(knowledge_records),
    )


# ============================================================================
# Documents
# ============================================================================

@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    """列出所有文档。KB 不可用时返回空数组而非 503。"""
    if not learning_manager.has_document_kb():
        return []
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
    except Exception as e:
        logger.error(f"Failed to list documents: {e}", exc_info=True)
        return []


@router.post("/documents/upload")
async def upload_document(
    request: DocumentUploadRequest,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    try:
        from app.avatar.learning.knowledge.document_kb import Document
        doc = Document(name=request.name, content=request.content, doc_type=request.doc_type)
        result = learning_manager.document_kb.add_document(doc)
        return {
            "success": True,
            "doc_id": result["doc_id"],
            "chunks_count": result["chunks_count"],
        }
    except Exception as e:
        logger.error(f"Document upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents/search", response_model=List[DocumentSearchResult])
async def search_documents(
    request: DocumentSearchRequest,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    try:
        matches = learning_manager.document_kb.search(query=request.query, n_results=request.max_results)
        return [
            DocumentSearchResult(
                chunk_id=m["chunk_id"],
                content=m["content"],
                doc_name=m["metadata"].get("doc_name", "Unknown"),
                distance=m.get("distance"),
            )
            for m in matches
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    try:
        deleted_count = learning_manager.document_kb.delete_document(doc_id)
        if deleted_count == 0:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
        return {"success": True, "deleted_chunks": deleted_count}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}/content")
async def get_document_content(
    doc_id: str,
    learning_manager: LearningManager = Depends(get_learning_manager),
):
    if not learning_manager.has_document_kb():
        raise HTTPException(status_code=503, detail="Document KB is not available")
    try:
        content = learning_manager.document_kb.get_document_content(doc_id)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found")
        return {"doc_id": doc_id, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Memories — user_prefs + episodic
# ============================================================================

@router.get("/memories", response_model=MemoriesResponse)
async def list_memories(
    limit: int = 50,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """返回用户画像偏好 + 任务执行历史（按时间倒序）。"""
    # 1. User prefs from knowledge.json  key: "user:default:prefs"
    user_prefs: List[UserPrefItem] = []
    prefs_data = memory_manager.get_knowledge("user:default:prefs") or {}
    for k, v in prefs_data.items():
        if k.startswith("_"):
            continue
        user_prefs.append(UserPrefItem(
            key=k,
            value=str(v),
            updated_at=datetime.utcnow().strftime("%Y-%m-%d"),
        ))

    # 2. Episodic from episodic.log — all task: records, newest first
    records = memory_manager.query_task_episodes(task_id="", limit=limit)
    records_sorted = sorted(records, key=lambda r: r.created_at, reverse=True)

    episodic: List[EpisodicItem] = []
    for rec in records_sorted:
        data = rec.data
        summary = data.get("summary", "")
        if not summary:
            extra = data.get("extra", {})
            summary = extra.get("user_request", rec.key)
        episodic.append(EpisodicItem(
            id=rec.key,
            summary=summary[:300],
            status=data.get("status", "unknown"),
            created_at=rec.created_at.strftime("%Y-%m-%d %H:%M"),
        ))

    return MemoriesResponse(user_prefs=user_prefs, episodic=episodic)


@router.post("/memories/search", response_model=List[MemorySearchResult])
async def search_memories(
    request: MemorySearchRequest,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """语义搜索历史任务（复用 vector_db）。"""
    results = memory_manager.search_similar_tasks(
        task_description=request.query,
        n_results=request.n_results,
    )
    out = []
    for r in results:
        meta = r.get("metadata", {})
        out.append(MemorySearchResult(
            id=meta.get("key", ""),
            summary=r.get("document", "")[:300],
            status=meta.get("status", "unknown"),
            created_at=meta.get("created_at", ""),
            distance=r.get("distance"),
        ))
    return out


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    """删除用户偏好项（key 格式: user:default:prefs/<field>）。"""
    if memory_id.startswith("user:default:prefs/"):
        field = memory_id.split("/", 1)[1]
        prefs = memory_manager.get_knowledge("user:default:prefs") or {}
        if field in prefs:
            del prefs[field]
            memory_manager.set_knowledge("user:default:prefs", prefs)
    return {"success": True, "memory_id": memory_id}


# ============================================================================
# Skills — static registry with example prompts
# ============================================================================

_SKILL_CATALOG: List[Dict[str, Any]] = [
    # File System
    {
        "name": "fs.read",
        "description": "读取文件内容",
        "category": "文件系统",
        "example_prompt": "读取 ~/Desktop/report.txt 的内容",
        "aliases": ["read_file", "file.read"],
    },
    {
        "name": "fs.write",
        "description": "写入或创建文件",
        "category": "文件系统",
        "example_prompt": "把这段文字保存到 ~/notes.txt",
        "aliases": ["write_file", "file.write"],
    },
    {
        "name": "fs.list",
        "description": "列出目录内容",
        "category": "文件系统",
        "example_prompt": "列出 ~/Documents 目录下的所有文件",
        "aliases": ["ls", "dir", "list_files"],
    },
    {
        "name": "fs.delete",
        "description": "删除文件或目录",
        "category": "文件系统",
        "example_prompt": "删除 ~/temp 目录",
        "aliases": ["rm", "remove_file"],
    },
    {
        "name": "fs.move",
        "description": "移动或重命名文件",
        "category": "文件系统",
        "example_prompt": "把 ~/old_name.txt 重命名为 ~/new_name.txt",
        "aliases": ["mv", "rename_file"],
    },
    {
        "name": "fs.copy",
        "description": "复制文件或目录",
        "category": "文件系统",
        "example_prompt": "把 ~/report.pdf 复制到 ~/backup/",
        "aliases": ["cp", "copy_file"],
    },
    # Python
    {
        "name": "python.run",
        "description": "执行 Python 代码，支持数据分析和可视化",
        "category": "代码执行",
        "example_prompt": "用 Python 计算 1 到 100 的所有质数",
        "aliases": ["run_python", "execute_python"],
    },
    # Network
    {
        "name": "net.get",
        "description": "发送 HTTP GET 请求",
        "category": "网络",
        "example_prompt": "获取 https://api.github.com/users/octocat 的信息",
        "aliases": ["http_get", "fetch"],
    },
    {
        "name": "net.post",
        "description": "发送 HTTP POST 请求",
        "category": "网络",
        "example_prompt": "向 https://httpbin.org/post 发送 JSON 数据",
        "aliases": ["http_post"],
    },
    # Memory
    {
        "name": "memory.store",
        "description": "存储信息到长期记忆",
        "category": "记忆",
        "example_prompt": "记住我的公司名叫 Acme Corp",
        "aliases": ["remember", "save_memory"],
    },
    {
        "name": "memory.search",
        "description": "语义搜索历史记忆",
        "category": "记忆",
        "example_prompt": "查找我之前提到过的公司信息",
        "aliases": ["recall", "search_memory"],
    },
    # Computer Control
    {
        "name": "screen.capture",
        "description": "截取当前屏幕",
        "category": "电脑控制",
        "example_prompt": "截一张当前屏幕的图",
        "aliases": ["screenshot"],
    },
    {
        "name": "mouse.click",
        "description": "模拟鼠标点击",
        "category": "电脑控制",
        "example_prompt": "点击屏幕坐标 (500, 300) 的位置",
        "aliases": ["click"],
    },
    {
        "name": "keyboard.type",
        "description": "模拟键盘输入文字",
        "category": "电脑控制",
        "example_prompt": "在当前输入框输入 Hello World",
        "aliases": ["type_text"],
    },
    # LLM Fallback
    {
        "name": "llm.fallback",
        "description": "直接调用 LLM 回答问题或生成内容",
        "category": "AI 推理",
        "example_prompt": "帮我写一封请假邮件",
        "aliases": ["ask", "chat", "generate"],
    },
]


@router.get("/skills/list", response_model=List[SkillItem])
async def list_skills():
    """返回内置 skill 列表，含分类和示例 prompt。"""
    return [SkillItem(**s) for s in _SKILL_CATALOG]


# ============================================================================
# MCP Tools — placeholder
# ============================================================================

@router.get("/mcp/tools", response_model=List[McpTool])
async def list_mcp_tools():
    """MCP Tools 预留接口，当前返回空数组。"""
    return []


# ============================================================================
# Cleanup
# ============================================================================

@router.post("/cleanup")
async def trigger_cleanup(
    days_to_keep: int = 30,
    memory_manager: MemoryManager = Depends(get_memory_manager),
):
    try:
        stats = memory_manager.cleanup_old_memories(
            days_to_keep=days_to_keep,
            keep_successful_tasks=True,
        )
        return {
            "success": True,
            "deleted_count": stats.get("episodic_deleted", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
