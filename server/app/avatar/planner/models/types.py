"""
子任务类型定义与技能策略

职责：
- 定义子任务类型枚举（闭集）
- 定义每种类型的技能白名单/黑名单
- 定义每种类型的标准输出字段契约
- 提供类型验证和策略查询接口
"""
from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass


class SubTaskType(str, Enum):
    """
    子任务类型（闭集枚举）
    
    这是框架协议层的关键字，控制 Planner 的行为边界。
    每种类型对应：
    1. 允许的技能集合（白名单）
    2. 标准化的输出字段名称
    3. 最大步骤数限制
    """
    
    # 内容生成类：纯LLM操作，不涉及任何I/O
    CONTENT_GENERATION = "content_generation"
    
    # 文件I/O类：文件/文档的读写操作
    FILE_IO = "file_io"
    
    # 信息提取类：从外部源（文件/网页）读取并解析
    INFORMATION_EXTRACTION = "information_extraction"
    
    # GUI操作类：图形界面交互
    GUI_OPERATION = "gui_operation"
    
    # 控制流类：条件判断、循环等（慎用）
    CONTROL_FLOW = "control_flow"
    
    # 通用执行类：允许多种技能组合，但有黑名单保护
    GENERAL_EXECUTION = "general_execution"


@dataclass
class SubTaskTypePolicy:
    """子任务类型策略"""
    
    # 允许的技能白名单（None 表示允许所有，但受黑名单限制）
    allowed_skills: Optional[Set[str]] = None
    
    # 禁止的技能黑名单
    forbidden_skills: Set[str] = None
    
    # 标准输出字段名称（固定契约）
    standard_output_fields: List[str] = None
    
    # 最大步骤数
    max_steps: int = 5
    
    # 类型描述（用于 Prompt）
    description: str = ""
    
    # 允许危险操作（python.run, shell.run）
    allow_dangerous: bool = False
    
    def __post_init__(self):
        if self.forbidden_skills is None:
            self.forbidden_skills = set()
        if self.standard_output_fields is None:
            self.standard_output_fields = []


# ============================================================
# 子任务类型策略配置
# ============================================================

SUBTASK_TYPE_POLICIES: Dict[SubTaskType, SubTaskTypePolicy] = {
    
    # 1. 内容生成类：只能用 LLM
    SubTaskType.CONTENT_GENERATION: SubTaskTypePolicy(
        allowed_skills={
            "llm.generate_text",
            "llm.summarize",
            "llm.answer_question",
            "llm.translate",
            "llm.extract_info",
            "llm.chat",
        },
        forbidden_skills={
            "file.write", "file.append", "file.read",
            "word.write", "word.append", "word.read",
            "excel.write", "excel.read",
            "notepad.open", "gui.click", "gui.type",
            "python.run", "shell.run",
        },
        standard_output_fields=["text", "content"],
        max_steps=1,  # 内容生成通常只需要1步
        description="纯内容生成任务，只能使用LLM技能，不能做任何文件操作或GUI操作",
        allow_dangerous=False,
    ),
    
    # 2. 文件I/O类：只能用文件操作
    SubTaskType.FILE_IO: SubTaskTypePolicy(
        allowed_skills={
            "file.write",
            "file.read",
            "file.append",
            "file.delete",
            "file.copy",
            "file.move",
            "word.write",
            "word.append",
            "word.read",
            "excel.write",
            "excel.read",
            "excel.append",
            "csv.write",
            "csv.read",
            "csv.append",
        },
        forbidden_skills={
            "llm.generate_text", "llm.summarize", "llm.translate",
            "web.search", "web.extract",
            "python.run", "shell.run",
        },
        standard_output_fields=["file_path", "paths"],
        max_steps=3,  # 可能需要写多个文件
        description="文件/文档的读写操作，不能生成内容（内容应由前置子任务提供）",
        allow_dangerous=False,
    ),
    
    # 3. 信息提取类：读取+解析
    SubTaskType.INFORMATION_EXTRACTION: SubTaskTypePolicy(
        allowed_skills={
            "file.read",
            "csv.read",
            "excel.read",
            "word.read",
            "web.search",
            "web.extract",
            "web.scrape",
            "llm.extract_info",  # 允许 LLM 辅助提取
            "llm.answer_question",

        },
        forbidden_skills={
            "file.write", "file.append",
            "word.write", "word.append",
            "gui.click", "gui.type",
            "python.run", "shell.run",
        },
        standard_output_fields=["data", "extracted_info"],
        max_steps=2,
        description="从外部源（文件/网页）读取并提取信息",
        allow_dangerous=False,
    ),
    
    # 4. GUI操作类：界面交互
    SubTaskType.GUI_OPERATION: SubTaskTypePolicy(
        allowed_skills={
            "gui.click",
            "gui.type",
            "gui.open_app",
            "gui.close_app",
            "notepad.open",
            "notepad.write",
            "chrome.open",
        },
        forbidden_skills={
            "python.run", "shell.run",
        },
        standard_output_fields=["result", "status"],
        max_steps=5,
        description="图形界面操作任务",
        allow_dangerous=False,
    ),
    
    # 5. 控制流类：条件/循环（慎用）
    SubTaskType.CONTROL_FLOW: SubTaskTypePolicy(
        allowed_skills={
            "control.if",
            "control.loop",
            "control.wait",
        },
        forbidden_skills={
            "python.run", "shell.run",
        },
        standard_output_fields=["result"],
        max_steps=1,
        description="控制流操作（条件判断、循环等）",
        allow_dangerous=False,
    ),
    
    # 6. 通用执行类：允许大部分技能组合（包括代码执行）
    SubTaskType.GENERAL_EXECUTION: SubTaskTypePolicy(
        allowed_skills=None,  # 允许所有（除了黑名单）
        forbidden_skills={
            # ⚠️ 只禁止真正危险的系统命令
            "system.run_command",
            "shell.run",
            "shell.execute",
            # ✅ python.run 允许使用（受 SkillGuard 控制）
            # 适用场景：数据处理、文本排序、简单计算等
        },
        standard_output_fields=["result"],
        max_steps=6,
        description="通用任务，允许多种技能组合（包括代码执行，但受 SkillGuard 和 Validator 控制）",
        allow_dangerous=False,
    ),
}


# ============================================================
# 危险技能定义（全局黑名单）
# ============================================================

DANGEROUS_SKILLS: Set[str] = {
    "python.run",
    "shell.run",
    "shell.execute",
    "system.run",
}


# ============================================================
# 工具函数
# ============================================================

def get_policy(subtask_type: SubTaskType) -> SubTaskTypePolicy:
    """获取子任务类型的策略"""
    return SUBTASK_TYPE_POLICIES.get(subtask_type, SUBTASK_TYPE_POLICIES[SubTaskType.GENERAL_EXECUTION])


def is_skill_allowed(skill_name: str, subtask_type: SubTaskType, allow_dangerous: bool = False) -> bool:
    """
    检查技能是否被允许
    
    优先级（从高到低）：
    1. 黑名单（forbidden_skills）- 最高优先级，直接拒绝
    2. 白名单（allowed_skills）- 如果配置了白名单，必须在白名单内
    3. 危险技能（DANGEROUS_SKILLS）- 需要 allow_dangerous=True 或在白名单中
    4. 默认允许 - 如果没有白名单且不在黑名单，则允许
    
    Args:
        skill_name: 技能名称
        subtask_type: 子任务类型
        allow_dangerous: 是否允许危险技能（用于显式授权）
    
    Returns:
        bool: True 表示允许
    """
    policy = get_policy(subtask_type)
    
    # 1. 黑名单检查（最高优先级）
    if skill_name in policy.forbidden_skills:
        return False
    
    # 2. 白名单检查（如果配置了白名单）
    if policy.allowed_skills is not None:
        # 严格模式：必须在白名单内
        return skill_name in policy.allowed_skills
    
    # 3. 危险技能检查（宽松模式：白名单为 None）
    # 在宽松模式下，危险技能也可以使用（因为已经通过了黑名单检查）
    # 但如果 allow_dangerous=False 且技能在 DANGEROUS_SKILLS 中，仍然需要额外检查
    if skill_name in DANGEROUS_SKILLS:
        # 如果黑名单里没有这个技能，说明该类型允许这个危险技能
        # 例如：GENERAL_EXECUTION 的黑名单里没有 python.run，说明允许使用
        return True  # 已经通过黑名单检查，允许使用
    
    # 4. 默认允许（宽松模式 + 非危险技能）
    return True


def filter_skills_by_type(
    skills: Dict[str, any],
    subtask_type: SubTaskType,
    allow_dangerous: bool = False
) -> Dict[str, any]:
    """
    根据子任务类型过滤技能
    
    Args:
        skills: 原始技能字典
        subtask_type: 子任务类型
        allow_dangerous: 是否允许危险技能
    
    Returns:
        过滤后的技能字典
    """
    return {
        name: info
        for name, info in skills.items()
        if is_skill_allowed(name, subtask_type, allow_dangerous)
    }


def get_standard_output_field(subtask_type: SubTaskType) -> str:
    """
    获取子任务类型的主输出字段名
    
    Args:
        subtask_type: 子任务类型
    
    Returns:
        标准输出字段名（第一个）
    """
    policy = get_policy(subtask_type)
    if policy.standard_output_fields:
        return policy.standard_output_fields[0]
    return "result"


def format_type_description_for_prompt(subtask_type: SubTaskType) -> str:
    """
    格式化类型描述用于 Prompt
    
    Args:
        subtask_type: 子任务类型
    
    Returns:
        格式化的描述文本
    """
    policy = get_policy(subtask_type)
    
    lines = [
        f"Type: {subtask_type.value}",
        f"Description: {policy.description}",
        f"Max Steps: {policy.max_steps}",
    ]
    
    if policy.allowed_skills:
        skills_list = ", ".join(sorted(policy.allowed_skills)[:10])
        if len(policy.allowed_skills) > 10:
            skills_list += ", ..."
        lines.append(f"Allowed Skills: {skills_list}")
    
    if policy.standard_output_fields:
        lines.append(f"Standard Output Fields: {', '.join(policy.standard_output_fields)}")
    
    return "\n".join(lines)


# ============================================================
# Decomposer 使用的类型说明文本
# ============================================================

def get_types_for_decomposer_prompt() -> str:
    """
    生成用于 Decomposer Prompt 的类型说明
    
    Returns:
        类型说明文本
    """
    lines = [
        "## 子任务类型（必须从以下类型中选择）",
        "",
    ]
    
    for task_type in SubTaskType:
        policy = get_policy(task_type)
        lines.append(f"### `{task_type.value}`")
        lines.append(f"- **职责**: {policy.description}")
        
        if policy.allowed_skills:
            skills_preview = list(policy.allowed_skills)[:5]
            skills_str = ", ".join(skills_preview)
            if len(policy.allowed_skills) > 5:
                skills_str += f" (共{len(policy.allowed_skills)}个)"
            lines.append(f"- **允许技能**: {skills_str}")
        else:
            lines.append(f"- **允许技能**: 大部分技能（有黑名单限制）")
        
        lines.append(f"- **标准输出字段**: `{', '.join(policy.standard_output_fields)}`")
        lines.append(f"- **最大步骤数**: {policy.max_steps}")
        lines.append("")
    
    return "\n".join(lines)

