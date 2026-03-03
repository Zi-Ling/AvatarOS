# avatar/artifact/resolver.py
"""
Artifact 引用解析器

检测用户输入中的引用词（如"刚才那个文件"），智能匹配对应的 Artifact
"""

import re
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolvedArtifact:
    """解析后的 Artifact 引用"""
    original_text: str
    resolved_text: str
    artifacts: List[Dict[str, Any]]
    confidence: float
    success: bool


# 中文引用模式
CHINESE_REFERENCE_PATTERNS = {
    # 时间类
    "recent_time": [
        r"刚才", r"刚刚", r"刚", 
        r"上次", r"上一次",
        r"之前", r"刚创建", r"刚生成",
        r"最近", r"新", r"最新",
    ],
    # 指示类
    "demonstrative": [
        r"那个", r"这个", r"该", 
        r"前面", r"上面",
        r"最后", r"第一个", r"第二个",
    ],
    # 类型类
    "type": {
        r"文件": "file",
        r"文档": "document", 
        r"图片": "image",
        r"图像": "image",
        r"报告": "document",
        r"代码": "code",
        r"数据": "data",
    }
}

# 英文引用模式
ENGLISH_REFERENCE_PATTERNS = {
    # 时间类
    "recent_time": [
        r"just now", r"recent", r"recently",
        r"last", r"previous", r"prev",
        r"earlier", r"latest", r"newest",
    ],
    # 指示类
    "demonstrative": [
        r"that", r"this", r"the",
        r"above", r"before",
        r"first", r"second", r"last",
    ],
    # 类型类
    "type": {
        r"file": "file",
        r"document": "document",
        r"doc": "document",
        r"image": "image",
        r"picture": "image",
        r"photo": "image",
        r"report": "document",
        r"code": "code",
        r"data": "data",
    }
}


def detect_artifact_reference(text: str) -> Tuple[bool, Dict[str, Any]]:
    """
    检测文本中是否包含 Artifact 引用
    
    返回:
        (has_reference, features) 
        - has_reference: 是否检测到引用
        - features: 提取的特征 {"time": ..., "type": ..., "demonstrative": ...}
    """
    features = {
        "time": None,
        "type": None,
        "demonstrative": False,
        "language": "zh" if any('\u4e00' <= c <= '\u9fff' for c in text) else "en"
    }
    
    has_reference = False
    
    # 选择语言模式
    patterns = CHINESE_REFERENCE_PATTERNS if features["language"] == "zh" else ENGLISH_REFERENCE_PATTERNS
    
    # 检测时间引用
    for time_word in patterns["recent_time"]:
        if re.search(time_word, text, re.IGNORECASE):
            features["time"] = "recent"
            has_reference = True
            break
    
    # 检测指示引用
    for demo_word in patterns["demonstrative"]:
        if re.search(demo_word, text, re.IGNORECASE):
            features["demonstrative"] = True
            has_reference = True
            break
    
    # 检测类型引用
    for type_word, type_value in patterns["type"].items():
        if re.search(type_word, text, re.IGNORECASE):
            features["type"] = type_value
            has_reference = True
            break
    
    return has_reference, features


def filter_artifacts_by_features(
    artifacts: List[Dict[str, Any]],
    features: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    根据特征筛选 Artifacts
    
    返回:
        筛选后的 Artifact 列表，按相关性排序
    """
    if not artifacts:
        return []
    
    filtered = []
    now = time.time()
    
    for artifact in artifacts:
        meta = artifact.get("meta", {})
        artifact_type = artifact.get("type", "")
        created_at = meta.get("created_at", 0)
        
        # 计算分数
        score = 0.0
        
        # 时间过滤
        if features.get("time") == "recent":
            age_minutes = (now - created_at) / 60
            if age_minutes < 5:
                score += 1.0
            elif age_minutes < 30:
                score += 0.5
            elif age_minutes < 60:
                score += 0.2
            else:
                continue  # 超过1小时，跳过
        
        # 类型过滤
        if features.get("type"):
            expected_type = features["type"]
            # 匹配类型（支持 "type:subtype" 格式）
            if expected_type in artifact_type:
                score += 1.0
            else:
                # 类型不匹配，降低分数
                score -= 0.5
        
        # 指示引用（"那个"、"这个"）通常指最近的
        if features.get("demonstrative"):
            # 越新分数越高
            age_minutes = (now - created_at) / 60
            if age_minutes < 1:
                score += 0.8
            elif age_minutes < 10:
                score += 0.5
            else:
                score += 0.2
        
        # 保存分数
        artifact_with_score = artifact.copy()
        artifact_with_score["_score"] = score
        filtered.append(artifact_with_score)
    
    # 按分数降序排序
    filtered.sort(key=lambda x: x["_score"], reverse=True)
    
    return filtered


async def resolve_artifact_references(
    text: str,
    session_id: str,
    memory_manager: Any,
    llm_client: Optional[Any] = None
) -> ResolvedArtifact:
    """
    解析文本中的 Artifact 引用
    
    策略：
    1. 规则引擎（快速匹配）
    2. 语义搜索（降级策略）
    
    参数:
        text: 用户输入文本
        session_id: 会话 ID
        memory_manager: MemoryManager 实例
        llm_client: LLM 客户端（用于消歧，可选）
    
    返回:
        ResolvedArtifact 对象
    """
    # 1. 检测是否有引用
    has_reference, features = detect_artifact_reference(text)
    
    # 如果规则引擎没检测到，尝试语义搜索
    if not has_reference:
        # 降级：使用语义搜索
        try:
            from .search import get_artifact_searcher
            
            artifact_searcher = get_artifact_searcher()
            scored_results = artifact_searcher.search(
                query=text,
                session_id=session_id,
                limit=3
            )
            
            if scored_results and scored_results[0].score > 0.6:
                # 语义匹配成功
                artifacts = [r.artifact for r in scored_results]
                confidence = scored_results[0].score
                
                return ResolvedArtifact(
                    original_text=text,
                    resolved_text=text,
                    artifacts=artifacts,
                    confidence=confidence,
                    success=True
                )
        except Exception:
            pass  # 语义搜索失败，继续返回 False
        
        return ResolvedArtifact(
            original_text=text,
            resolved_text=text,
            artifacts=[],
            confidence=0.0,
            success=False
        )
    
    # 2. 从 Session 获取 Artifacts
    try:
        session_data = memory_manager.get_session_context(session_id)
        if not session_data or "artifacts" not in session_data:
            return ResolvedArtifact(
                original_text=text,
                resolved_text=text,
                artifacts=[],
                confidence=0.0,
                success=False
            )
        
        all_artifacts = session_data["artifacts"]
        if not all_artifacts:
            return ResolvedArtifact(
                original_text=text,
                resolved_text=text,
                artifacts=[],
                confidence=0.0,
                success=False
            )
        
    except Exception as e:
        logger.error(f"[ArtifactResolver] Failed to get artifacts: {e}")
        return ResolvedArtifact(
            original_text=text,
            resolved_text=text,
            artifacts=[],
            confidence=0.0,
            success=False
        )
    
    # 3. 筛选候选 Artifacts
    candidates = filter_artifacts_by_features(all_artifacts, features)
    
    if not candidates:
        return ResolvedArtifact(
            original_text=text,
            resolved_text=text,
            artifacts=[],
            confidence=0.0,
            success=False
        )
    
    # 4. 计算置信度
    top_score = candidates[0]["_score"]
    
    # 如果只有一个候选且分数高，直接返回
    if len(candidates) == 1 and top_score > 0.8:
        confidence = 0.9
    elif top_score > 1.5:
        confidence = 0.85
    elif top_score > 1.0:
        confidence = 0.7
    else:
        confidence = 0.5
    
    # 5. 构建结果（返回 top-1 或 top-3）
    if confidence > 0.7:
        # 高置信度，返回 top-1
        resolved_artifacts = [candidates[0]]
    else:
        # 中等置信度，返回 top-3 供用户选择
        resolved_artifacts = candidates[:3]
    
    # 6. 替换文本（可选，这里只标记）
    resolved_text = text  # 暂时不做文本替换，由调用方决定
    
    return ResolvedArtifact(
        original_text=text,
        resolved_text=resolved_text,
        artifacts=resolved_artifacts,
        confidence=confidence,
        success=True
    )


def format_artifact_for_display(artifact: Dict[str, Any]) -> str:
    """格式化 Artifact 用于显示"""
    meta = artifact.get("meta", {})
    filename = meta.get("filename", "Unknown")
    artifact_type = artifact.get("type", "file")
    uri = artifact.get("uri", "")
    
    # 时间
    created_at = meta.get("created_at", 0)
    age_minutes = int((time.time() - created_at) / 60)
    if age_minutes < 1:
        time_str = "刚刚"
    elif age_minutes < 60:
        time_str = f"{age_minutes}分钟前"
    else:
        hours = age_minutes // 60
        time_str = f"{hours}小时前"
    
    return f"{filename} ({artifact_type}, {time_str})"

