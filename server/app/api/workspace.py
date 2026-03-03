# app/api/workspace.py
"""
工作目录 API
提供工作目录的查询、切换、验证等功能
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
import logging

from app.core.workspace.manager import get_workspace_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspace", tags=["workspace"])


class SetWorkspaceRequest(BaseModel):
    path: str


class ValidatePathRequest(BaseModel):
    path: str


@router.get("/current")
async def get_current_workspace():
    """获取当前工作目录信息"""
    try:
        manager = get_workspace_manager()
        current = manager.get_workspace()
        
        return {
            "path": str(current),
            "absolute_path": str(current.absolute()),
            "exists": current.exists(),
            "name": current.name or "workspace"
        }
    except Exception as e:
        logger.error(f"获取工作目录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/set")
async def set_workspace(request: SetWorkspaceRequest):
    """设置工作目录"""
    try:
        manager = get_workspace_manager()
        new_path = manager.set_workspace(request.path)
        
        return {
            "success": True,
            "path": str(new_path),
            "absolute_path": str(new_path.absolute()),
            "message": "工作目录已切换"
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"设置工作目录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/recent")
async def get_recent_paths():
    """获取最近使用的路径列表"""
    try:
        manager = get_workspace_manager()
        recent = manager.get_recent_paths()
        
        return {
            "recent_paths": recent
        }
    except Exception as e:
        logger.error(f"获取最近路径失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_to_default():
    """重置到默认工作目录"""
    try:
        manager = get_workspace_manager()
        default_path = manager.reset_to_default()
        
        return {
            "success": True,
            "path": str(default_path),
            "message": "已重置到默认工作目录"
        }
    except Exception as e:
        logger.error(f"重置工作目录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/validate")
async def validate_path(request: ValidatePathRequest):
    """验证路径是否有效"""
    try:
        manager = get_workspace_manager()
        result = manager.validate_path(request.path)
        return result
    except Exception as e:
        logger.error(f"验证路径失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select-folder")
async def select_folder():
    """
    打开系统文件选择器（需要桌面环境）
    返回用户选择的文件夹路径
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        root = tk.Tk()
        root.withdraw()  # 隐藏主窗口
        root.attributes('-topmost', True)  # 置顶
        
        folder_path = filedialog.askdirectory(
            title="选择工作目录",
            initialdir=str(Path.home())
        )
        
        root.destroy()
        
        if not folder_path:
            raise HTTPException(status_code=400, detail="用户取消选择")
        
        return {"path": folder_path}
        
    except ImportError:
        raise HTTPException(
            status_code=501, 
            detail="系统不支持文件选择器（需要安装 tkinter）"
        )
    except Exception as e:
        logger.error(f"打开文件选择器失败: {e}")
        raise HTTPException(status_code=500, detail=f"打开文件选择器失败: {e}")

