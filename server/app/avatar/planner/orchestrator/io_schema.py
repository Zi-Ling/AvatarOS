"""
IO Schema - 子任务类型的输入输出角色定义

职责：
- 定义 IO 字段的语义角色（TEXT / FILE_PATH / RESULT 等）
- 维护"子任务类型 → 期望输入角色"的映射表
- 为 Bridge 层提供类型检查的依据

这是纯数据结构模块，不包含业务逻辑。
"""
from enum import Enum
from typing import Dict
from ..models.types import SubTaskType


class IOFieldRole(str, Enum):
    """
    IO 字段的语义角色
    
    用于描述一个输入/输出字段在数据流中的角色，
    而不仅仅是字段名称。
    """
    TEXT = "text"              # 文本内容（字符串）
    FILE_PATH = "file_path"    # 单个文件路径
    FILE_PATHS = "paths"       # 多个文件路径（列表）
    RESULT = "result"          # 泛型结果（任意类型）
    JSON = "json"              # JSON 数据（字典或列表）
    NONE = "none"              # 不关心 / 可选


# ============================================================
# 子任务类型 → 期望输入字段角色的映射
# ============================================================

SUBTASK_INPUT_ROLE_SPEC: Dict[SubTaskType, Dict[str, IOFieldRole]] = {
    
    # 1. content_generation（内容生成类）
    #    只能消费文本类输入，绝不能直接消费文件路径
    SubTaskType.CONTENT_GENERATION: {
        "text": IOFieldRole.TEXT,
        "content": IOFieldRole.TEXT,
        "prompt": IOFieldRole.TEXT,
        "input": IOFieldRole.TEXT,  # 通用文本输入字段
    },
    
    # 2. file_io（文件操作类）
    #    根据具体技能不同，可能消费文本或路径
    SubTaskType.FILE_IO: {
        "file_path": IOFieldRole.FILE_PATH,
        "paths": IOFieldRole.FILE_PATHS,
        "content": IOFieldRole.TEXT,
        "text": IOFieldRole.TEXT,
        "data": IOFieldRole.TEXT,  # 用于写入文件的数据
    },
    
    # 3. information_extraction（信息提取类）
    #    可以消费文本或路径，但如果消费路径通常需要先读取
    SubTaskType.INFORMATION_EXTRACTION: {
        "text": IOFieldRole.TEXT,
        "content": IOFieldRole.TEXT,
        "file_path": IOFieldRole.FILE_PATH,
        "url": IOFieldRole.TEXT,  # Web URL（虽然是路径，但处理方式不同）
    },
    
    # 4. gui_operation（GUI 操作类）
    #    通常不太关心输入类型，更多是操作指令
    SubTaskType.GUI_OPERATION: {
        "text": IOFieldRole.TEXT,
        "file_path": IOFieldRole.FILE_PATH,
        "result": IOFieldRole.RESULT,
    },
    
    # 5. control_flow（控制流类）
    #    条件/循环控制，可能需要各种类型的输入
    SubTaskType.CONTROL_FLOW: {
        "condition": IOFieldRole.TEXT,
        "result": IOFieldRole.RESULT,
    },
    
    # 6. general_execution（通用执行类）
    #    最宽松，允许各种类型的输入
    SubTaskType.GENERAL_EXECUTION: {
        "file_path": IOFieldRole.FILE_PATH,
        "paths": IOFieldRole.FILE_PATHS,
        "text": IOFieldRole.TEXT,
        "content": IOFieldRole.TEXT,
        "result": IOFieldRole.RESULT,
        "data": IOFieldRole.TEXT,
        "input": IOFieldRole.TEXT,
    },
}


# ============================================================
# 工具函数
# ============================================================

def get_expected_input_role(
    subtask_type: SubTaskType,
    field_name: str
) -> IOFieldRole:
    """
    获取某个子任务类型的指定输入字段的期望角色
    
    Args:
        subtask_type: 子任务类型
        field_name: 输入字段名称
    
    Returns:
        IOFieldRole: 期望的角色（如果未定义，返回 NONE）
    
    Examples:
        >>> get_expected_input_role(SubTaskType.CONTENT_GENERATION, "text")
        IOFieldRole.TEXT
        
        >>> get_expected_input_role(SubTaskType.FILE_IO, "file_path")
        IOFieldRole.FILE_PATH
    """
    role_spec = SUBTASK_INPUT_ROLE_SPEC.get(subtask_type, {})
    return role_spec.get(field_name, IOFieldRole.NONE)


def is_text_role(role: IOFieldRole) -> bool:
    """判断角色是否为文本类型"""
    return role == IOFieldRole.TEXT


def is_path_role(role: IOFieldRole) -> bool:
    """判断角色是否为路径类型"""
    return role in (IOFieldRole.FILE_PATH, IOFieldRole.FILE_PATHS)


def requires_text_but_has_path(
    subtask_type: SubTaskType,
    input_key: str,
    input_value: str
) -> bool:
    """
    判断是否出现"需要文本但提供了路径"的类型不匹配
    
    Args:
        subtask_type: 子任务类型
        input_key: 输入字段名称
        input_value: 输入值（可能包含引用）
    
    Returns:
        bool: True 表示需要桥接修正
    
    Examples:
        >>> requires_text_but_has_path(
        ...     SubTaskType.CONTENT_GENERATION,
        ...     "text",
        ...     "${subtask_2.output.file_path}"
        ... )
        True
    """
    # 检查期望角色
    expected_role = get_expected_input_role(subtask_type, input_key)
    
    if not is_text_role(expected_role):
        return False
    
    # 检查实际提供的是否是路径
    if not isinstance(input_value, str):
        return False
    
    # 简单检测：引用字符串中包含 ".file_path" 或 ".paths"
    return ".file_path" in input_value or ".paths" in input_value


# ============================================================
# 输出字段的标准化映射
# ============================================================

# 每种子任务类型的标准输出字段名称
# 这与 types.py 中的 SUBTASK_TYPE_POLICIES.standard_output_fields 保持一致
STANDARD_OUTPUT_FIELDS: Dict[SubTaskType, list[str]] = {
    SubTaskType.CONTENT_GENERATION: ["text", "content"],
    SubTaskType.FILE_IO: ["file_path", "paths"],
    SubTaskType.INFORMATION_EXTRACTION: ["data", "extracted_info"],
    SubTaskType.GUI_OPERATION: ["result", "status"],
    SubTaskType.CONTROL_FLOW: ["result"],
    SubTaskType.GENERAL_EXECUTION: ["result"],
}


def get_standard_text_output_field() -> str:
    """获取文本输出的标准字段名"""
    return "content"


def get_standard_path_output_field() -> str:
    """获取路径输出的标准字段名"""
    return "file_path"

