# app/db/serialization.py
"""
数据库序列化工具
提供通用的序列化机制，将任意 Python 对象转换为 JSON-safe 类型
"""
from datetime import datetime, date, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


def serialize_for_db(obj: Any, max_depth: int = 10, _current_depth: int = 0) -> Any:
    """
    递归序列化对象为 JSON-safe 类型
    
    支持的类型转换：
    - datetime/date/time -> ISO string
    - Path -> string
    - Decimal -> float
    - Enum -> value
    - Pydantic Model -> dict (via .dict())
    - dataclass -> dict (via dataclasses.asdict)
    - dict -> 递归序列化
    - list/tuple/set -> 递归序列化
    - 其他 -> str() 或标记为不可序列化
    
    Args:
        obj: 要序列化的对象
        max_depth: 最大递归深度，防止循环引用
        _current_depth: 当前递归深度（内部使用）
    
    Returns:
        JSON-safe 对象（str, int, float, bool, None, dict, list）
    """
    # 防止无限递归
    if _current_depth > max_depth:
        logger.warning(f"Serialization max depth ({max_depth}) exceeded")
        return "<max_depth_exceeded>"
    
    # None
    if obj is None:
        return None
    
    # 基础类型（JSON 原生支持）
    if isinstance(obj, (str, int, float, bool)):
        return obj
    
    # 日期时间类型
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, time):
        return obj.isoformat()
    
    # Path
    if isinstance(obj, Path):
        return str(obj)
    
    # Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    
    # Enum
    if isinstance(obj, Enum):
        return obj.value
    
    # Bytes
    if isinstance(obj, bytes):
        try:
            return obj.decode('utf-8')
        except (UnicodeDecodeError, AttributeError):
            return f"<bytes: {len(obj)} bytes>"
    
    # Dict（递归处理）
    if isinstance(obj, dict):
        try:
            return {
                str(k): serialize_for_db(v, max_depth, _current_depth + 1) 
                for k, v in obj.items()
            }
        except Exception as e:
            logger.warning(f"Error serializing dict: {e}")
            return {"error": f"serialization_failed: {str(e)}"}
    
    # List/Tuple（递归处理）
    if isinstance(obj, (list, tuple)):
        try:
            return [serialize_for_db(item, max_depth, _current_depth + 1) for item in obj]
        except Exception as e:
            logger.warning(f"Error serializing list/tuple: {e}")
            return [f"<serialization_failed: {str(e)}>"]
    
    # Set（转为列表）
    if isinstance(obj, set):
        try:
            return [serialize_for_db(item, max_depth, _current_depth + 1) for item in obj]
        except Exception as e:
            logger.warning(f"Error serializing set: {e}")
            return []
    
    # Pydantic Model（has .dict() method）
    if hasattr(obj, 'dict') and callable(getattr(obj, 'dict')):
        try:
            # Pydantic v2 使用 model_dump(), v1 使用 dict()
            if hasattr(obj, 'model_dump'):
                return serialize_for_db(obj.model_dump(), max_depth, _current_depth + 1)
            else:
                return serialize_for_db(obj.dict(), max_depth, _current_depth + 1)
        except Exception as e:
            logger.warning(f"Error serializing Pydantic model: {e}")
            return {"error": f"pydantic_serialization_failed: {str(e)}"}
    
    # Dataclass（has __dataclass_fields__）
    if hasattr(obj, '__dataclass_fields__'):
        try:
            from dataclasses import asdict
            return serialize_for_db(asdict(obj), max_depth, _current_depth + 1)
        except Exception as e:
            logger.warning(f"Error serializing dataclass: {e}")
            return {"error": f"dataclass_serialization_failed: {str(e)}"}
    
    # 其他对象：尝试转为字符串
    try:
        # 尝试 JSON 序列化测试
        import json
        json.dumps(obj)
        return obj  # 如果能序列化，直接返回
    except (TypeError, ValueError, OverflowError):
        pass
    
    # 最后降级：转为字符串
    try:
        obj_str = str(obj)
        # 避免超长字符串
        if len(obj_str) > 1000:
            obj_str = obj_str[:997] + "..."
        return f"<{type(obj).__name__}: {obj_str}>"
    except Exception:
        return f"<unserializable: {type(obj).__name__}>"

