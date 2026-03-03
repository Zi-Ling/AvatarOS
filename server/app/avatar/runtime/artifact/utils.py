# avatar/artifact/path_normalizer.py
"""
Artifact 工具函数

提供类型推断、元数据提取等实用功能
"""

import os
import time
from typing import Dict, Any, Optional, Tuple
from pathlib import Path


# 文件扩展名 → Artifact 类型映射
FILE_TYPE_MAP = {
    # 文本文件
    ".txt": ("file", "text"),
    ".md": ("file", "markdown"),
    ".log": ("file", "log"),
    ".json": ("file", "json"),
    ".yaml": ("file", "yaml"),
    ".yml": ("file", "yaml"),
    ".xml": ("file", "xml"),
    ".csv": ("data", "csv"),
    
    # 文档
    ".docx": ("document", "word"),
    ".doc": ("document", "word"),
    ".pdf": ("document", "pdf"),
    ".xlsx": ("data", "excel"),
    ".xls": ("data", "excel"),
    ".pptx": ("document", "powerpoint"),
    ".ppt": ("document", "powerpoint"),
    
    # 图片
    ".png": ("image", "png"),
    ".jpg": ("image", "jpeg"),
    ".jpeg": ("image", "jpeg"),
    ".gif": ("image", "gif"),
    ".bmp": ("image", "bmp"),
    ".svg": ("image", "svg"),
    ".webp": ("image", "webp"),
    
    # 代码
    ".py": ("code", "python"),
    ".js": ("code", "javascript"),
    ".ts": ("code", "typescript"),
    ".java": ("code", "java"),
    ".cpp": ("code", "cpp"),
    ".c": ("code", "c"),
    ".go": ("code", "go"),
    ".rs": ("code", "rust"),
    ".html": ("code", "html"),
    ".css": ("code", "css"),
    
    # 压缩包
    ".zip": ("archive", "zip"),
    ".tar": ("archive", "tar"),
    ".gz": ("archive", "gzip"),
    ".rar": ("archive", "rar"),
    ".7z": ("archive", "7z"),
}


# 技能名称 → Artifact 类型映射（已有技能的默认类型）
SKILL_TYPE_MAP = {
    "file.write": ("file", "text"),
    "file.save": ("file", "text"),
    "file.create": ("file", "text"),
    "word.create": ("document", "word"),
    "word.write": ("document", "word"),
    "excel.create": ("data", "excel"),
    "image.generate": ("image", "generated"),
    "web.download": ("file", "download"),
    "archive.zip": ("archive", "zip"),
    "pdf.create": ("document", "pdf"),
    "pdf.merge": ("document", "pdf"),
    "computer.screenshot": ("image", "screenshot"),
}


def infer_artifact_type(
    uri: str,
    skill_name: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """
    推断 Artifact 类型
    
    参数:
        uri: 文件路径或 URI
        skill_name: 创建该 Artifact 的技能名称
        output: 技能的输出结果
        
    返回:
        (type, subtype) 元组
        
    策略优先级:
        1. 从技能名称推断（如果在 SKILL_TYPE_MAP 中）
        2. 从文件扩展名推断
        3. 从 output 中的提示推断
        4. 默认为 ("file", "unknown")
    """
    # 策略 1: 从技能名称推断
    if skill_name and skill_name in SKILL_TYPE_MAP:
        return SKILL_TYPE_MAP[skill_name]
    
    # 策略 2: 从文件扩展名推断
    if uri:
        ext = Path(uri).suffix.lower()
        if ext in FILE_TYPE_MAP:
            return FILE_TYPE_MAP[ext]
    
    # 策略 3: 从 output 中的提示推断
    if output and isinstance(output, dict):
        # 检查是否有明确的类型提示
        if "artifact_type" in output:
            artifact_type = output["artifact_type"]
            if isinstance(artifact_type, tuple) and len(artifact_type) == 2:
                return artifact_type
            elif isinstance(artifact_type, str):
                return (artifact_type, "unknown")
        
        # 检查是否是图片（有 image/screenshot 字段）
        if "image" in output or "screenshot" in output:
            return ("image", "screenshot")
        
        # 检查是否是代码（有 code 字段）
        if "code" in output or "source_code" in output:
            return ("code", "generated")
    
    # 策略 4: 默认
    return ("file", "unknown")


def extract_artifact_metadata(
    uri: str,
    skill_name: str,
    step_id: str,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    提取 Artifact 元数据
    
    参数:
        uri: 文件路径或 URI
        skill_name: 创建技能
        step_id: 步骤 ID
        task_id: 任务 ID
        session_id: 会话 ID
        output: 技能输出
        
    返回:
        元数据字典
    """
    meta = {
        "skill": skill_name,
        "step_id": step_id,
        "created_at": time.time(),
    }
    
    # 添加任务和会话信息
    if task_id:
        meta["task_id"] = task_id
    if session_id:
        meta["session_id"] = session_id
    
    # 提取文件信息（如果是本地文件）
    if uri and os.path.exists(uri):
        try:
            stat = os.stat(uri)
            meta["filename"] = os.path.basename(uri)
            meta["size"] = stat.st_size  # 字节
            meta["mime_type"] = _guess_mime_type(uri)
            
            # 格式化大小（人类可读）
            meta["size_human"] = _format_size(stat.st_size)
        except Exception:
            # 文件访问失败，跳过
            pass
    else:
        # 非本地文件，至少提取文件名
        if uri:
            meta["filename"] = os.path.basename(uri)
    
    # 从 output 中提取额外信息
    if output and isinstance(output, dict):
        # 保留有用的字段
        useful_fields = [
            "description", "tags", "category", "author", 
            "width", "height",  # 图片尺寸
            "pages",  # PDF 页数
            "duration",  # 视频/音频时长
        ]
        
        for field in useful_fields:
            if field in output:
                meta[field] = output[field]
        
        # 保留简短的输出摘要
        if "message" in output:
            meta["message"] = str(output["message"])[:200]
    
    return meta


def _guess_mime_type(file_path: str) -> str:
    """简单的 MIME 类型推断"""
    ext = Path(file_path).suffix.lower()
    
    mime_map = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".xml": "application/xml",
        ".csv": "text/csv",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".zip": "application/zip",
        ".py": "text/x-python",
        ".js": "text/javascript",
    }
    
    return mime_map.get(ext, "application/octet-stream")


def _format_size(bytes_size: int) -> str:
    """格式化文件大小为人类可读格式"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

