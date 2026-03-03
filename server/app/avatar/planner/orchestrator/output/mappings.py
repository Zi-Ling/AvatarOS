"""
技能字段映射配置
"""
from typing import Dict


# 技能特定的字段映射规则
# 格式：{ "技能名": { "LLM期望字段": "实际输出字段" } }
SKILL_FIELD_MAPPINGS: Dict[str, Dict[str, str]] = {
    "file.write": {
        "result_file": "path",
        "output_file": "path",
        "file_path": "path",
        "output_path": "path",
        "result_path": "path",
        "written_file": "path",
        "saved_file": "path",
    },
    "file.write_text": {
        "result_file": "path",
        "output_file": "path",
        "file_path": "path",
        "output_path": "path",
        "result_path": "path",
    },
    "file.read": {
        "file_content": "content",
        "text": "content",
        "data": "content",
        "result": "content",
        "file_text": "content",
    },
    "file.read_text": {
        "file_content": "content",
        "text": "content",
        "data": "content",
        "result": "content",
    },
    # 通用的路径字段映射（适用于所有文件类技能）
    "_universal_": {
        "result_file": "path",
        "output_file": "path",
        "file_path": "path",
        "output_path": "path",
        "result_path": "path",
    }
}

