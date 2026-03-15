from fastapi import APIRouter, HTTPException, Query, Body
from typing import List, Optional, Dict, Any
from pathlib import Path
from pydantic import BaseModel
import os
import mimetypes
import logging
import sys

from app.core.config import config
from app.core.workspace.manager import get_workspace_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fs", tags=["filesystem"])

class RenameRequest(BaseModel):
    path: str
    new_name: str

class MoveRequest(BaseModel):
    src_path: str
    dst_path: str

class CopyRequest(BaseModel):
    src_path: str
    dst_path: str

class CreateFolderRequest(BaseModel):
    path: str

class WriteFileRequest(BaseModel):
    path: str
    content: str
    check_exists: bool = False  # 是否检查文件是否已存在

def _get_safe_path(path_str: str) -> Path:
    """
    Resolve path relative to workspace and ensure it's safe.
    """
    # 使用 workspace_manager 获取当前工作目录
    workspace = get_workspace_manager().get_workspace()
    
    # Remove leading slashes/dots to prevent absolute paths
    clean_path = path_str.lstrip("/").lstrip("\\")
    target_path = (workspace / clean_path).resolve()
    
    # Security check: Ensure target is within workspace
    if not str(target_path).startswith(str(workspace.resolve())):
        raise HTTPException(status_code=403, detail="Access denied: Path outside workspace")
        
    return target_path

@router.get("/absolute-path")
async def get_absolute_path(path: str = Query("", description="Relative path")):
    """
    Get absolute path for a given relative path.
    """
    try:
        target_path = _get_safe_path(path)
        return {
            "relative_path": path,
            "absolute_path": str(target_path.absolute())
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
async def list_files(path: str = Query("", description="Relative path to list")):
    """
    List files and directories in the workspace.
    """
    try:
        target_dir = _get_safe_path(path)
        
        if not target_dir.exists():
            raise HTTPException(status_code=404, detail="Directory not found")
        
        if not target_dir.is_dir():
            raise HTTPException(status_code=400, detail="Path is not a directory")
            
        items = []
        # Sort: Directories first, then files
        with os.scandir(target_dir) as it:
            entries = list(it)
            entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))
            
            for entry in entries:
                # Skip hidden files/dirs
                if entry.name.startswith("."):
                    continue
                    
                stat = entry.stat()
                item_type = "dir" if entry.is_dir() else "file"
                
                # Guess mime type for files
                mime_type = None
                if item_type == "file":
                    mime_type, _ = mimetypes.guess_type(entry.name)
                
                items.append({
                    "name": entry.name,
                    "path": str(Path(path) / entry.name).replace("\\", "/"),
                    "type": item_type,
                    "size": stat.st_size if item_type == "file" else 0,
                    "modified": stat.st_mtime,
                    "mime_type": mime_type
                })
                
        return {
            "path": path,
            "items": items
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/read")
async def read_file(path: str = Query(..., description="Relative path to read")):
    """
    Read file content. Currently limits to text files < 1MB.
    """
    try:
        target_file = _get_safe_path(path)
        
        if not target_file.exists():
            raise HTTPException(status_code=404, detail="File not found")
            
        if not target_file.is_file():
            raise HTTPException(status_code=400, detail="Path is not a file")
            
        # Size check (1MB limit for safety)
        if target_file.stat().st_size > 1024 * 1024:
             raise HTTPException(status_code=400, detail="File too large to preview")
             
        # Try to read as text
        try:
            content = target_file.read_text(encoding="utf-8")
            return {"content": content, "type": "text"}
        except UnicodeDecodeError:
            # Binary file?
             raise HTTPException(status_code=400, detail="Binary file preview not supported")
             
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/write")
async def write_file(request: WriteFileRequest):
    """
    Write content to a file. Creates file if it doesn't exist.
    """
    try:
        target_file = _get_safe_path(request.path)
        
        # 如果需要检查文件是否已存在（用于新建文件）
        if request.check_exists and target_file.exists():
            raise HTTPException(
                status_code=409, 
                detail=f"文件已存在: {target_file.name}"
            )
        
        # Create parent directories if needed
        target_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write content
        target_file.write_text(request.content, encoding="utf-8")
        
        logger.info(f"File written: {target_file}")
        return {
            "success": True,
            "message": "File saved successfully",
            "path": request.path
        }
             
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to write file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reveal")
async def reveal_in_explorer(path: str = Query("", description="Relative path to reveal")):
    """
    Open the file explorer and select the file (Windows/Mac).
    """
    import platform
    import subprocess
    
    try:
        target_path = _get_safe_path(path)
        
        if not target_path.exists():
             raise HTTPException(status_code=404, detail="Path not found")

        system_name = platform.system()
        
        if system_name == "Windows":
            # Windows: explorer /select, "path"
            # Only works for files. For dirs, just open it.
            path_str = str(target_path).replace("/", "\\")
            if target_path.is_file():
                subprocess.run(f'explorer /select,"{path_str}"', shell=True)
            else:
                os.startfile(path_str)
                
        elif system_name == "Darwin": # macOS
            subprocess.run(["open", "-R", str(target_path)])
            
        else: # Linux
            # xdg-open opens the file/dir, doesn't necessarily "reveal"
            subprocess.run(["xdg-open", str(target_path.parent if target_path.is_file() else target_path)])
            
        return {"success": True, "message": f"Revealed {target_path}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reveal path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reveal path: {e}")

@router.post("/open")
async def open_file(path: str = Query(..., description="Relative path to open")):
    """
    Open file with system default application.
    """
    import platform
    import subprocess
    
    try:
        target_path = _get_safe_path(path)
        
        if not target_path.exists():
             raise HTTPException(status_code=404, detail="Path not found")

        system_name = platform.system()
        
        if system_name == "Windows":
            try:
                # 使用绝对路径（更可靠）
                os.startfile(str(target_path.absolute()))
            except OSError as e:
                # 所有打开失败的情况，都尝试打开"打开方式"对话框
                # WinError 1155: No application is associated with the specified file
                # WinError 2147221003: 其他关联问题
                logger.warning(f"无法直接打开文件 {target_path}，尝试打开'打开方式'对话框: {e}")
                try:
                    # 使用异步方式打开对话框，避免阻塞
                    import asyncio
                    import ctypes
                    
                    async def open_with_dialog():
                        # 启动 OpenAs 对话框
                        process = await asyncio.create_subprocess_shell(
                            f'rundll32.exe shell32.dll,OpenAs_RunDLL "{target_path}"',
                            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
                        )
                        
                        # 等待一小段时间让对话框启动
                        await asyncio.sleep(0.3)
                        
                        # 尝试将对话框窗口置顶
                        try:
                            # 查找 "打开方式" 对话框窗口
                            user32 = ctypes.windll.user32
                            # HWND_TOPMOST = -1, SWP_NOMOVE | SWP_NOSIZE = 0x0003
                            # 枚举所有顶级窗口，找到 "打开方式" 对话框
                            def enum_callback(hwnd, _):
                                length = user32.GetWindowTextLengthW(hwnd)
                                if length > 0:
                                    buff = ctypes.create_unicode_buffer(length + 1)
                                    user32.GetWindowTextW(hwnd, buff, length + 1)
                                    title = buff.value
                                    # 如果窗口标题包含文件名或"打开方式"，就将其置顶
                                    if target_path.name in title or "打开方式" in title or "Open With" in title:
                                        user32.SetForegroundWindow(hwnd)
                                        user32.BringWindowToTop(hwnd)
                                return True
                            
                            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                            user32.EnumWindows(EnumWindowsProc(enum_callback), 0)
                        except Exception as win_error:
                            logger.debug(f"无法将对话框置顶: {win_error}")
                    
                    # 在后台运行，不阻塞主线程
                    asyncio.create_task(open_with_dialog())
                    
                except Exception as fallback_error:
                    logger.error(f"打开'打开方式'对话框也失败: {fallback_error}")
                    raise HTTPException(
                        status_code=500, 
                        detail=f"无法打开文件，请手动在文件管理器中打开: {str(e)}"
                    )
                
        elif system_name == "Darwin": # macOS
            try:
                subprocess.run(["open", str(target_path)], check=True)
            except subprocess.CalledProcessError as e:
                # macOS fallback: 打开"打开方式"对话框
                subprocess.run(["open", "-a", "Finder", str(target_path)], check=False)
            
        else: # Linux
            try:
                subprocess.run(["xdg-open", str(target_path)], check=True)
            except subprocess.CalledProcessError as e:
                # Linux fallback: 打开文件管理器
                subprocess.run(["xdg-open", str(target_path.parent)], check=False)
            
        return {"success": True, "message": f"Opened {target_path}"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to open path: {e}")
        # 不再抛出错误，而是返回成功（因为已经尝试打开"打开方式"对话框）
        return {"success": True, "message": f"已尝试打开文件，如果没有反应请手动选择打开程序"}

@router.delete("/delete")
async def delete_file_or_dir(path: str = Query(..., description="Relative path to delete")):
    """
    Delete a file or directory (recursively if directory).
    """
    import shutil
    
    try:
        target_path = _get_safe_path(path)
        
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        # Additional safety check: prevent deleting workspace root
        if target_path.resolve() == config.avatar_workspace.resolve():
            raise HTTPException(status_code=403, detail="Cannot delete workspace root")
        
        # Delete file or directory
        if target_path.is_file():
            target_path.unlink()
            logger.info(f"Deleted file: {target_path}")
            return {"success": True, "message": f"File deleted: {target_path.name}", "type": "file"}
        elif target_path.is_dir():
            shutil.rmtree(target_path)
            logger.info(f"Deleted directory: {target_path}")
            return {"success": True, "message": f"Directory deleted: {target_path.name}", "type": "directory"}
        else:
            raise HTTPException(status_code=400, detail="Path is neither file nor directory")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

@router.post("/rename")
async def rename_file_or_dir(request: RenameRequest):
    """
    Rename a file or directory.
    """
    try:
        target_path = _get_safe_path(request.path)
        
        if not target_path.exists():
            raise HTTPException(status_code=404, detail="Path not found")
        
        # Get parent directory
        parent_dir = target_path.parent
        new_path = parent_dir / request.new_name
        
        # Security check: Ensure new path is also within workspace
        if not str(new_path.resolve()).startswith(str(config.avatar_workspace.resolve())):
            raise HTTPException(status_code=403, detail="Access denied: New path outside workspace")
        
        # Check if target already exists
        if new_path.exists():
            raise HTTPException(status_code=400, detail="A file or folder with that name already exists")
        
        # Rename
        target_path.rename(new_path)
        logger.info(f"Renamed {target_path} to {new_path}")
        
        return {"success": True, "message": f"Renamed to {request.new_name}"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to rename: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rename: {e}")

@router.post("/create-folder")
async def create_folder(request: CreateFolderRequest):
    """
    Create a new folder.
    """
    try:
        target_path = _get_safe_path(request.path)
        
        # Check if already exists
        if target_path.exists():
            raise HTTPException(status_code=400, detail="Folder already exists")
        
        # Create folder (including parents if needed)
        target_path.mkdir(parents=True, exist_ok=False)
        logger.info(f"Created folder: {target_path}")
        
        return {"success": True, "message": f"Folder created: {target_path.name}"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create folder: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create folder: {e}")

@router.post("/move")
async def move_file_or_dir(request: MoveRequest):
    """
    Move a file or directory to a new location.
    """
    try:
        src_path = _get_safe_path(request.src_path)
        dst_path = _get_safe_path(request.dst_path)
        
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source path not found")
        
        # Check if destination already exists
        if dst_path.exists():
            raise HTTPException(status_code=400, detail="Destination already exists")
        
        # Ensure destination parent directory exists
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Move the file or directory
        src_path.rename(dst_path)
        logger.info(f"Moved {src_path} to {dst_path}")
        
        return {"success": True, "message": f"Moved to {request.dst_path}"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to move: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to move: {e}")

@router.post("/copy")
async def copy_file_or_dir(request: CopyRequest):
    """
    Copy a file or directory to a new location.
    """
    import shutil
    
    try:
        src_path = _get_safe_path(request.src_path)
        dst_path = _get_safe_path(request.dst_path)
        
        if not src_path.exists():
            raise HTTPException(status_code=404, detail="Source path not found")
        
        # Check if destination already exists
        if dst_path.exists():
            raise HTTPException(status_code=400, detail="Destination already exists")
        
        # Ensure destination parent directory exists
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the file or directory
        if src_path.is_file():
            shutil.copy2(src_path, dst_path)
            logger.info(f"Copied file {src_path} to {dst_path}")
        elif src_path.is_dir():
            shutil.copytree(src_path, dst_path)
            logger.info(f"Copied directory {src_path} to {dst_path}")
        else:
            raise HTTPException(status_code=400, detail="Path is neither file nor directory")
        
        return {"success": True, "message": f"Copied to {request.dst_path}"}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to copy: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to copy: {e}")

