# app/avatar/skills/common/serialization.py

from datetime import datetime, date
from decimal import Decimal
from typing import Any
import json

def serialize_for_excel(value: Any) -> Any:
    """
    Convert arbitrary Python objects into Excel-safe values.
    """
    if value is None:
        return None

    # Basic scalar types
    if isinstance(value, (str, int, float, bool)):
        return value

    # Datetime types
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    # Decimal
    if isinstance(value, Decimal):
        return float(value)

    # Pydantic / dict / list
    if isinstance(value, (dict, list)):
        # 保守策略：JSON 字符串
        return json.dumps(value, ensure_ascii=False)

    # Fallback：显式字符串化（最后兜底）
    return str(value)
