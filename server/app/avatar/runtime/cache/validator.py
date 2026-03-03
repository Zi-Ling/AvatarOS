"""
计划缓存 - 验证器

包含：
- PlanValidator: 统一的计划验证器，负责判定哪些计划可缓存、哪些不可缓存
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional, Any, List, Set, TYPE_CHECKING

from .models import CacheRejectReason

if TYPE_CHECKING:
    from app.avatar.planner.models import Task, Step

logger = logging.getLogger(__name__)


# ============================================================================
# 计划验证器
# ============================================================================

class PlanValidator:
    """
    统一的计划验证器（集中式判定，不散落在各个技能）
    
    缓存策略分级：
    1. 必须缓存：纯文件 I/O、纯文本处理、纯数据读写
    2. 绝对不缓存：fallback/chat、动态代码、GUI 自动化、不稳定网络
    3. 有条件缓存：结构化 LLM 输出、明确路径的文档操作
    4. 缓存门槛：参数推断、未知字段、artifact 依赖、成功率
    """
    
    # ======== 一、必须缓存（高复用 + 低上下文依赖）======== #
    
    # 纯文件 I/O（确定路径/文件名）
    MUST_CACHE_FILE_IO = {
        "file.write", "file.write_text", "file.read", "file.read_text",
        "file.copy", "file.move", "file.rename", "file.delete",
        "directory.create", "directory.list", "directory.delete"
    }
    
    # 纯文本处理（输入输出明确）
    MUST_CACHE_TEXT_PROCESSING = {
        "text.replace", "text.split", "text.extract", "text.format",
        "text.upper", "text.lower", "text.trim", "text.concat"
    }
    
    # 纯数据读写（表格/JSON/CSV 的确定操作）
    MUST_CACHE_DATA_IO = {
        "csv.read", "csv.write", "csv.append",
        "json.read", "json.write", "json.parse",
        "excel.read", "excel.write_table"  # 写入固定 sheet/range
    }
    
    # ======== 二、绝对不缓存（高风险 / 强环境依赖 / 不可复用）======== #
    
    # fallback / chat / 任意 LLM 自由生成类
    NEVER_CACHE_LLM_GENERATION = {
        "llm.fallback", "fallback", "llm.chat",
        "llm.generate", "llm.generate_text", "llm.create"
    }
    
    # python.run / shell 执行类（动态代码）
    NEVER_CACHE_DYNAMIC_CODE = {
        "python.run", "python.execute", "python.eval",
        "shell.run", "shell.execute", "system.exec"
    }
    
    # GUI/桌面自动化（屏幕/窗口/点击）
    NEVER_CACHE_GUI_AUTOMATION = {
        "computer.screen.capture", "computer.screen.info",
        "mouse.click", "mouse.move", "mouse.drag",
        "keyboard.type", "keyboard.press", "keyboard.hotkey",
        "app.open", "app.close", "app.focus", "app.list"
    }
    
    # 网络/外部系统不稳定依赖
    NEVER_CACHE_UNSTABLE_NETWORK = {
        "browser.open", "browser.navigate", "browser.click",
        "http.get", "http.post", "http.request",  # 外部 API
        "web.scrape", "web.extract", "web.search"  # 爬取
    }
    
    # ======== 三、有条件缓存（需要额外检查）======== #
    
    # LLM 但属于"结构化小输出"（需要检查输出长度和 schema）
    CONDITIONAL_CACHE_LLM_STRUCTURED = {
        "llm.extract", "llm.classify", "llm.summarize_short",
        "llm.parse_json", "llm.extract_fields"
    }
    
    # Excel/Word/PDF 写入类（需要检查路径明确性）
    CONDITIONAL_CACHE_DOCUMENT_OPS = {
        "excel.write", "word.write", "pdf.create",
        "excel.format", "word.format"
    }
    
    _skill_registry = None  # Lazy load
    
    @classmethod
    def get_skill_cache_category(cls, skill_name: str) -> str:
        """
        获取技能的缓存分类（用于可观测性）
        
        Args:
            skill_name: 技能名称
        
        Returns:
            缓存分类：must_cache、never_cache、conditional_cache、unknown
        """
        if skill_name in cls.MUST_CACHE_FILE_IO:
            return "must_cache:file_io"
        elif skill_name in cls.MUST_CACHE_TEXT_PROCESSING:
            return "must_cache:text_processing"
        elif skill_name in cls.MUST_CACHE_DATA_IO:
            return "must_cache:data_io"
        elif skill_name in cls.NEVER_CACHE_LLM_GENERATION:
            return "never_cache:llm_generation"
        elif skill_name in cls.NEVER_CACHE_DYNAMIC_CODE:
            return "never_cache:dynamic_code"
        elif skill_name in cls.NEVER_CACHE_GUI_AUTOMATION:
            return "never_cache:gui_automation"
        elif skill_name in cls.NEVER_CACHE_UNSTABLE_NETWORK:
            return "never_cache:unstable_network"
        elif skill_name in cls.CONDITIONAL_CACHE_LLM_STRUCTURED:
            return "conditional_cache:llm_structured"
        elif skill_name in cls.CONDITIONAL_CACHE_DOCUMENT_OPS:
            return "conditional_cache:document_ops"
        else:
            return "unknown"
    
    @classmethod
    def _get_skill_registry(cls):
        """延迟加载 SkillRegistry"""
        if cls._skill_registry is None:
            from app.avatar.skills.registry import skill_registry
            cls._skill_registry = skill_registry
        return cls._skill_registry
    
    @staticmethod
    def validate(task: "Task") -> tuple[bool, Optional[CacheRejectReason], Optional[str]]:
        """
        验证任务是否可缓存（精细化策略 v2）
        
        核心原则：
        1. 必须缓存：纯文件 I/O、纯文本处理、纯数据读写
        2. 绝对不缓存：LLM生成、动态代码、GUI、网络
        3. 有条件缓存：结构化LLM、文档操作（需额外检查）
        4. 硬门槛：参数推断、未知字段、artifact依赖、成功率不足
        
        Returns:
            (is_valid, reject_reason, detail_message)
        """
        from app.avatar.planner.models import TaskStatus, StepStatus
        
        # ======== 步骤 0：基础检查 ======== #
        
        # 0.1 检查执行是否成功
        if task.status != TaskStatus.SUCCESS:
            return False, CacheRejectReason.EXECUTION_FAILED, f"Task status: {task.status.name}"
        
        # 0.2 检查关键步骤是否全部成功
        if not task.steps:
            return False, CacheRejectReason.SCHEMA_INCOMPLETE, "No steps in task"
        
        failed_steps = [s for s in task.steps if s.status == StepStatus.FAILED]
        if failed_steps:
            return False, CacheRejectReason.EXECUTION_FAILED, f"{len(failed_steps)} steps failed"
        
        # ======== 步骤 1：绝对不缓存检查（一票否决）======== #
        
        has_cacheable_skill = False  # 至少要有一个可缓存的技能
        
        for step in task.steps:
            skill_name = step.skill_name
            
            # 1.1 LLM 自由生成（fallback/chat/generate）—— 一票否决
            if skill_name in PlanValidator.NEVER_CACHE_LLM_GENERATION:
                return False, CacheRejectReason.CONTAINS_FALLBACK, \
                    f"Contains LLM generation skill: {skill_name}"
            
            # 1.2 动态代码执行（python.run/shell）—— 一票否决
            if skill_name in PlanValidator.NEVER_CACHE_DYNAMIC_CODE:
                return False, CacheRejectReason.DYNAMIC_CODE, \
                    f"Contains dynamic code execution: {skill_name}"
            
            # 1.3 GUI/桌面自动化 —— 一票否决
            if skill_name in PlanValidator.NEVER_CACHE_GUI_AUTOMATION:
                return False, CacheRejectReason.GUI_AUTOMATION, \
                    f"Contains GUI automation: {skill_name}"
            
            # 1.4 不稳定网络依赖 —— 一票否决
            if skill_name in PlanValidator.NEVER_CACHE_UNSTABLE_NETWORK:
                return False, CacheRejectReason.UNSTABLE_NETWORK, \
                    f"Contains unstable network operation: {skill_name}"
            
            # 1.5 记录是否有"必须缓存"的技能
            if skill_name in (PlanValidator.MUST_CACHE_FILE_IO | 
                             PlanValidator.MUST_CACHE_TEXT_PROCESSING | 
                             PlanValidator.MUST_CACHE_DATA_IO):
                has_cacheable_skill = True
        
        # 1.6 如果全是"有条件缓存"或"未知技能"，也需要至少通过后续检查
        # 这里暂时放宽，但如果全是未知技能，会在后面的检查中拒绝
        
        # ======== 步骤 2：参数完整性检查（使用 SkillRegistry）======== #
        
        registry = PlanValidator._get_skill_registry()
        
        for step in task.steps:
            skill_name = step.skill_name
            
            # 2.1 获取技能的 required fields
            required_fields = PlanValidator._get_required_params(registry, skill_name)
            
            if required_fields:
                # 检查必需参数是否都存在且非空
                missing_fields = []
                for field in required_fields:
                    if field not in step.params or step.params[field] is None or step.params[field] == "":
                        missing_fields.append(field)
                
                if missing_fields:
                    # ⚠️ 注意：缺少必需参数说明可能是推断出来的（硬门槛）
                    return False, CacheRejectReason.MISSING_REQUIRED_PARAMS, \
                        f"Step {step.id} ({skill_name}) missing required params: {missing_fields}"
            
            # 2.2 检查是否有未知参数（LLM 发明的参数名）—— 硬门槛
            known_fields = PlanValidator._get_all_params(registry, skill_name)
            if known_fields:
                unknown_fields = [k for k in step.params.keys() if k not in known_fields]
                if unknown_fields:
                    # ⚠️ LLM 发明参数名，说明对 schema 理解不稳定
                    return False, CacheRejectReason.UNKNOWN_PARAMS, \
                        f"Step {step.id} ({skill_name}) has unknown params: {unknown_fields}"
        
        # ======== 步骤 3：参数来源检查（硬门槛：是否是推断出来的）======== #
        
        # ⚠️ 这是最关键的一步：只要有参数是"猜"出来的，就不缓存
        for step in task.steps:
            if PlanValidator._has_inferred_params(step):
                return False, CacheRejectReason.PARAMS_INFERRED, \
                    f"Step {step.id} has inferred params (not reliable for caching)"
        
        # ======== 步骤 4：参数可模板化检查 ======== #
        
        for step in task.steps:
            # 4.1 检查参数是否可模板化（不包含随机长文本）
            if not PlanValidator._is_params_templateable(step.params):
                return False, CacheRejectReason.NOT_TEMPLATEABLE, \
                    f"Step {step.id} params not templateable (contains long/random text)"
            
            # 4.2 检查是否依赖 artifact 残留（未显式提供）—— 硬门槛
            if PlanValidator._has_artifact_dependency(step.params, task):
                return False, CacheRejectReason.ARTIFACT_DEPENDENCY, \
                    f"Step {step.id} depends on implicit artifacts"
        
        # ======== 步骤 5：有条件缓存检查 ======== #
        
        for step in task.steps:
            skill_name = step.skill_name
            
            # 5.1 结构化 LLM 输出（检查输出长度 < 500字符）
            if skill_name in PlanValidator.CONDITIONAL_CACHE_LLM_STRUCTURED:
                if not PlanValidator._check_llm_output_size(step):
                    return False, CacheRejectReason.OUTPUT_TOO_LONG, \
                        f"Step {step.id} LLM output too long (>500 chars, not cacheable)"
                
                # 额外检查：确保有明确的 schema
                if not PlanValidator._check_llm_schema_complete(step):
                    return False, CacheRejectReason.SCHEMA_INCOMPLETE, \
                        f"Step {step.id} LLM output schema incomplete"
            
            # 5.2 文档操作（检查路径明确性）
            if skill_name in PlanValidator.CONDITIONAL_CACHE_DOCUMENT_OPS:
                if not PlanValidator._check_path_explicit(step.params):
                    return False, CacheRejectReason.NOT_TEMPLATEABLE, \
                        f"Step {step.id} document path not explicit (depends on state)"
        
        # ======== 步骤 6：计划稳定性检查 ======== #
        
        # 6.1 检查步骤数量是否合理（1-10步）
        if len(task.steps) > 10:
            return False, CacheRejectReason.UNSTABLE_PLAN, \
                f"Too many steps ({len(task.steps)}) - complex plans are unstable"
        
        # 6.2 检查是否全是"未知技能"（说明是特殊/罕见任务）
        if not has_cacheable_skill:
            # 检查是否全是未知技能
            all_unknown = all(
                PlanValidator.get_skill_cache_category(s.skill_name) == "unknown"
                for s in task.steps
            )
            if all_unknown:
                return False, CacheRejectReason.NON_CACHEABLE_SKILL, \
                    "All skills are unknown/non-cacheable"
        
        # ======== 全部通过 ======== #
        
        logger.debug(
            f"✅ PlanCache validation passed: {task.id} "
            f"(steps={len(task.steps)}, cacheable_skills={has_cacheable_skill})"
        )
        return True, None, None
    
    @staticmethod
    def _get_required_params(registry, skill_name: str) -> List[str]:
        """
        从 SkillRegistry 获取技能的必需参数
        
        Args:
            registry: SkillRegistry 实例
            skill_name: 技能名称
        
        Returns:
            必需参数列表
        """
        try:
            skill_cls = registry.get(skill_name)
            if skill_cls is None:
                logger.debug(f"Skill not found in registry: {skill_name}")
                return []
            
            spec = skill_cls.spec
            if spec.input_model is None:
                return []
            
            # 从 Pydantic model 获取 required fields
            schema = spec.input_model.model_json_schema()
            required = schema.get("required", [])
            
            return required
        except Exception as e:
            logger.debug(f"Failed to get required params for {skill_name}: {e}")
            return []
    
    @staticmethod
    def _get_all_params(registry, skill_name: str) -> Set[str]:
        """
        从 SkillRegistry 获取技能的所有参数（包括可选参数）
        
        Args:
            registry: SkillRegistry 实例
            skill_name: 技能名称
        
        Returns:
            所有参数名的集合
        """
        try:
            skill_cls = registry.get(skill_name)
            if skill_cls is None:
                logger.debug(f"Skill not found in registry: {skill_name}")
                return set()
            
            spec = skill_cls.spec
            if spec.input_model is None:
                return set()
            
            # 从 Pydantic model 获取所有字段
            schema = spec.input_model.model_json_schema()
            properties = schema.get("properties", {})
            
            return set(properties.keys())
        except Exception as e:
            logger.debug(f"Failed to get all params for {skill_name}: {e}")
            return set()
    
    @staticmethod
    def _is_params_templateable(params: Dict[str, Any]) -> bool:
        """
        判断参数是否可模板化（更严格的检查）
        
        拒绝条件：
        1. 超长字符串（>1000字符）—— 可能是 LLM 生成的长文本
        2. 包含 UUID/随机 token（非 ID 字段）—— 不可泛化
        3. 包含时间戳（非日期字段）—— 时效性强
        4. 包含长随机字符串（>50字符且看起来随机）—— 不可复用
        """
        for key, value in params.items():
            if not isinstance(value, str):
                # 递归检查嵌套结构
                if isinstance(value, dict):
                    if not PlanValidator._is_params_templateable(value):
                        return False
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and not PlanValidator._is_params_templateable(item):
                            return False
                continue
            
            # ========== 字符串参数检查 ========== #
            
            # 1. 超长字符串（>1000字符）
            if len(value) > 1000:
                logger.debug(f"Param '{key}' too long: {len(value)} chars (max 1000)")
                return False
            
            # 2. 检测 UUID 格式（除非是 ID 字段）
            if re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value.lower()):
                if "id" not in key.lower():
                    logger.debug(f"Param '{key}' contains UUID but not an ID field: {value}")
                    return False
            
            # 3. 检测时间戳（Unix timestamp，10位或13位数字）
            if re.match(r'^\d{10,13}$', value):
                if key.lower() not in ("timestamp", "time", "created_at", "updated_at", "date"):
                    logger.debug(f"Param '{key}' looks like timestamp but not a time field: {value}")
                    return False
            
            # 4. 检测长随机字符串（>50字符且包含大量随机字符）
            if len(value) > 50:
                # 计算字符串的"随机性"：字母数字混合 + 没有空格
                has_mixed_case = any(c.isupper() for c in value) and any(c.islower() for c in value)
                has_digits = any(c.isdigit() for c in value)
                no_spaces = ' ' not in value
                
                # 如果满足"随机字符串"特征（且不是常见的内容字段）
                if has_mixed_case and has_digits and no_spaces:
                    if key.lower() not in ("content", "text", "message", "description", "prompt", "query", "code"):
                        logger.debug(f"Param '{key}' looks like random string: {value[:50]}...")
                        return False
            
            # 5. 检测 token/secret/password（安全敏感）
            if key.lower() in ("token", "secret", "password", "api_key", "access_token", "auth_token"):
                # 如果值看起来是真实的 token（长度>20且包含随机字符）
                if len(value) > 20 and re.search(r'[A-Za-z0-9+/]{20,}', value):
                    logger.debug(f"Param '{key}' looks like sensitive token/secret")
                    return False
            
            # 6. 检测日期时间字符串（如果太具体，不可泛化）
            # 例如：2024-01-15 14:32:18
            if re.search(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}', value):
                if key.lower() not in ("datetime", "timestamp", "created_at", "updated_at"):
                    logger.debug(f"Param '{key}' contains specific datetime: {value}")
                    return False
        
        return True
    
    @staticmethod
    def _has_artifact_dependency(params: Dict[str, Any], task: "Task") -> bool:
        """
        检查是否依赖 artifact 残留（未显式提供的文件路径）—— 硬门槛
        
        核心原则：如果引用了"最近的文件"但 goal 中未显式提供，说明依赖隐式状态
        
        Args:
            params: 步骤参数
            task: 任务对象
        
        Returns:
            是否依赖隐式 artifact
        """
        goal_lower = task.goal.lower()
        
        # 1. 检查文件路径参数
        for key, value in params.items():
            if not isinstance(value, str):
                continue
            
            value_lower = value.lower()
            
            # 1.1 如果参数名是文件路径相关
            if key in ("path", "file_path", "filename", "relative_path", "source_path", "target_path", "input_file", "output_file"):
                
                # 检查是否包含隐式引用关键词（一票否决）
                implicit_keywords = [
                    "latest", "recent", "last", "previous", "current",
                    "temp_", "tmp_", "cache_", "session_",
                    "最近", "最新", "上一个", "当前", "临时"
                ]
                if any(kw in value_lower for kw in implicit_keywords):
                    logger.debug(f"Artifact dependency detected: {key}={value} (implicit keyword)")
                    return True
                
                # 检查路径是否在 goal 中明确提到
                # 提取文件名部分（去掉路径）
                filename = value.split('/')[-1].split('\\')[-1]
                
                # 如果文件名不在 goal 中，且不是"明显的用户输入"
                if filename and filename not in task.goal and filename not in goal_lower:
                    # 额外检查：是否是"生成的文件名"（包含时间戳/UUID）
                    has_timestamp = re.search(r'\d{4}-\d{2}-\d{2}|\d{8}|\d{10,13}', filename)
                    has_uuid = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}', filename.lower())
                    
                    if has_timestamp or has_uuid:
                        logger.debug(f"Artifact dependency detected: {key}={value} (generated filename with timestamp/uuid)")
                        return True
                    
                    # 如果文件名看起来很"随机"（长度>20且包含随机字符）
                    if len(filename) > 20 and re.search(r'[0-9a-f]{8,}', filename.lower()):
                        logger.debug(f"Artifact dependency detected: {key}={value} (random-looking filename)")
                        return True
            
            # 1.2 检查是否引用了"上一步的输出"（例如 {step_1.output}）
            if re.search(r'\{step_\d+\.\w+\}|\$\{step_\d+\.\w+\}', value):
                logger.debug(f"Artifact dependency detected: {key}={value} (references previous step output)")
                return True
            
            # 1.3 检查是否引用了"变量"（例如 {latest_file}、{artifact_path}）
            if re.search(r'\{[a-z_]+\}|\$\{[a-z_]+\}', value_lower):
                # 但排除常见的模板变量（这些可能是合法的）
                if not re.search(r'\{(filename|content|text|query|prompt|name|id)\}', value_lower):
                    logger.debug(f"Artifact dependency detected: {key}={value} (uses variable reference)")
                    return True
        
        return False
    
    @staticmethod
    def _check_llm_output_size(step: "Step") -> bool:
        """
        检查 LLM 输出大小是否合理（用于结构化输出）
        
        Args:
            step: 步骤对象
        
        Returns:
            输出是否在合理范围内（< 500 字符）
        """
        # 如果 step 有 result，检查输出长度
        if hasattr(step, 'result') and step.result:
            result = step.result
            
            # 尝试从 result 中提取文本内容
            text_content = None
            if isinstance(result, str):
                text_content = result
            elif isinstance(result, dict):
                # 常见的输出字段
                for key in ["text", "content", "output", "result", "data"]:
                    if key in result:
                        text_content = str(result[key])
                        break
            
            if text_content and len(text_content) > 500:
                logger.debug(f"LLM output too long: {len(text_content)} chars (max 500)")
                return False
        
        return True
    
    @staticmethod
    def _check_llm_schema_complete(step: "Step") -> bool:
        """
        检查 LLM 结构化输出的 schema 是否完整
        
        Args:
            step: 步骤对象
        
        Returns:
            schema 是否完整且稳定
        """
        # 检查参数中是否有明确的 schema 定义
        if hasattr(step, 'result') and step.result:
            result = step.result
            
            # 如果输出是 dict，检查是否有必需的 key
            if isinstance(result, dict):
                # 检查是否有明确的结构（至少有1个非空字段）
                if not result or all(v is None or v == "" for v in result.values()):
                    logger.debug(f"LLM output schema incomplete: empty or all None values")
                    return False
                
                # 检查是否包含随机 ID（说明不稳定）
                for key, value in result.items():
                    if isinstance(value, str) and key.lower() not in ("id", "task_id", "step_id"):
                        # 检测 UUID 格式
                        if re.match(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value.lower()):
                            logger.debug(f"LLM output contains random UUID: {key}={value}")
                            return False
        
        return True
    
    @staticmethod
    def _check_path_explicit(params: Dict[str, Any]) -> bool:
        """
        检查路径是否明确（不依赖"打开已有文档并定位"）
        
        Args:
            params: 步骤参数
        
        Returns:
            路径是否明确
        """
        # 检查文件路径相关参数是否明确
        for key, value in params.items():
            if key in ("path", "file_path", "filename", "relative_path", "target_path", "source_path"):
                if isinstance(value, str):
                    # 拒绝条件：包含"当前打开"、"活动文档"等状态依赖
                    if any(kw in value.lower() for kw in ["current", "active", "opened", "focused"]):
                        return False
        
        return True
    
    @staticmethod
    def _has_inferred_params(step: "Step") -> bool:
        """
        检查是否有推断的参数（硬门槛：推断参数 = 不可靠）
        
        核心原则：只要参数看起来是"猜"出来的，就不缓存
        - 参数值看起来是"默认值"/"占位符"
        
        Args:
            step: 步骤对象
        
        Returns:
            是否有推断的参数
        """
        # 检查 step.metadata 中的 param_source 标记
        if hasattr(step, 'metadata') and step.metadata:
            metadata = step.metadata
            
            # 如果有 param_source 字段，检查是否有"inferred"标记
            if isinstance(metadata, dict) and "param_source" in metadata:
                param_source = metadata["param_source"]
                
                # param_source 格式示例：{"filename": "inferred", "content": "provided"}
                if isinstance(param_source, dict):
                    for param_name, source in param_source.items():
                        if source in ["inferred", "guessed", "assumed", "fallback", "default"]:
                            logger.debug(f"Step {step.id} param '{param_name}' was inferred (source={source})")
                            return True
                # 但我们可以做更严格的检查
        
        # 方法2：启发式检查参数值是否看起来是"默认值"
        for param_name, param_value in step.params.items():
            if isinstance(param_value, str):
                # 检查是否是常见的占位符/默认值
                placeholder_patterns = [
                    "default", "unknown", "temp", "tmp", "placeholder",
                    "todo", "fixme", "tbd", "tbc", "unnamed"
                ]
                if any(pattern in param_value.lower() for pattern in placeholder_patterns):
                    logger.debug(f"Step {step.id} param '{param_name}' looks like placeholder: {param_value}")
                    return True
                
                # 检查是否是空字符串（但被标记为必需参数）
                if param_value == "" and param_name in step.params:
                    # 空字符串可能是推断失败
                    logger.debug(f"Step {step.id} param '{param_name}' is empty string")
                    # 但这个会在 MISSING_REQUIRED_PARAMS 检查中捕获，这里不重复
        
        # 方法3：检查参数数量是否异常少（可能是推断失败/部分推断）
        # 但这个比较难判定，暂时不做
        
        return False
