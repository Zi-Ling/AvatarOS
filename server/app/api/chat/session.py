# app/api/chat/session.py
"""
会话管理接口
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
from pathlib import Path
import json
import uuid
import logging
from filelock import FileLock

logger = logging.getLogger(__name__)

from app.api.chat.models import (
    SessionResponse,
    SessionListResponse,
    SessionHistoryResponse,
    MessageResponse,
)
from app.core.config import config, AVATAR_HOME


router = APIRouter()


def get_sessions_dir() -> Path:
    """获取会话存储目录（聊天历史，系统级数据，存 ~/.avatar/.sessions）"""
    sessions_dir = AVATAR_HOME / ".sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_session_file(session_id: str) -> Path:
    """获取会话文件路径"""
    return get_sessions_dir() / f"{session_id}.json"


def _get_session_lock(session_id: str) -> FileLock:
    """获取会话文件锁"""
    lock_dir = get_sessions_dir() / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    return FileLock(lock_dir / f"{session_id}.lock", timeout=5)


@router.get("/", response_model=SessionListResponse)
async def list_sessions():
    """
    获取会话列表
    """
    sessions_dir = get_sessions_dir()
    sessions = []
    
    for session_file in sessions_dir.glob("*.json"):
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append(SessionResponse(
                    id=data["id"],
                    title=data.get("title", "新对话"),
                    created_at=data["created_at"],
                    updated_at=data["updated_at"],
                    message_count=len(data.get("messages", [])),
                ))
        except Exception as e:
            logger.warning(f"读取会话失败 {session_file}: {e}")
            continue
    
    # 按更新时间倒序
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    
    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.post("/", response_model=SessionResponse)
async def create_session():
    """
    创建新会话
    """
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    
    session_data = {
        "id": session_id,
        "title": "新对话",
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    
    session_file = get_session_file(session_id)
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)
    
    return SessionResponse(
        id=session_id,
        title="新对话",
        created_at=now,
        updated_at=now,
        message_count=0,
    )


@router.get("/{session_id}", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str):
    """
    获取会话历史消息
    """
    session_file = get_session_file(session_id)
    
    if not session_file.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    
    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    messages = [
        MessageResponse(
            id=msg["id"],
            role=msg["role"],
            content=msg["content"],
            timestamp=msg["timestamp"],
        )
        for msg in data.get("messages", [])
    ]
    
    return SessionHistoryResponse(
        session_id=session_id,
        messages=messages,
    )


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """
    删除会话
    """
    session_file = get_session_file(session_id)
    
    if not session_file.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    
    session_file.unlink()
    
    return {"message": "会话已删除", "session_id": session_id}


@router.put("/{session_id}/title")
async def update_session_title(session_id: str, title: str):
    """
    更新会话标题
    """
    session_file = get_session_file(session_id)
    
    if not session_file.exists():
        raise HTTPException(status_code=404, detail="会话不存在")
    
    with open(session_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    data["title"] = title
    data["updated_at"] = datetime.now().isoformat()
    
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return {"message": "标题已更新", "title": title}


def save_message_to_session(session_id: str, role: str, content: str) -> str:
    """
    保存消息到会话（内部函数，带文件锁）
    
    Returns:
        message_id
    """
    session_file = get_session_file(session_id)
    lock = _get_session_lock(session_id)
    
    with lock:
        # 如果会话不存在，创建新会话
        if not session_file.exists():
            now = datetime.now().isoformat()
            session_data = {
                "id": session_id,
                "title": "新对话",
                "created_at": now,
                "updated_at": now,
                "messages": [],
            }
        else:
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        
        # 添加消息
        message_id = str(uuid.uuid4())
        message = {
            "id": message_id,
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        
        session_data["messages"].append(message)
        session_data["updated_at"] = datetime.now().isoformat()
        
        # 自动生成标题（第一条用户消息）
        if session_data["title"] == "新对话" and role == "user":
            session_data["title"] = content[:30] + ("..." if len(content) > 30 else "")
        
        # 保存
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)
    
    return message_id


def get_session_messages(session_id: str) -> list[dict]:
    """
    获取会话的所有消息（内部函数，带文件锁）
    
    Returns:
        [{"role": "user", "content": "..."}, ...]
    """
    session_file = get_session_file(session_id)
    
    if not session_file.exists():
        return []
    
    lock = _get_session_lock(session_id)
    with lock:
        with open(session_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    
    return [
        {"role": msg["role"], "content": msg["content"]}
        for msg in data.get("messages", [])
    ]

