"""
计划缓存 - 数据模型和工具类

包含：
- CacheRejectReason: 缓存拒绝原因枚举
- StepSkeleton: 步骤骨架（模板）
- QualityMetrics: 缓存质量指标
- PlanTemplate: 计划模板（缓存对象）
- CacheKeyGenerator: 缓存键生成器
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.planner.models import Step


# ============================================================================
# 枚举定义
# ============================================================================

class CacheRejectReason(str, Enum):
    """缓存拒绝原因（可观测）"""
    CONTAINS_FALLBACK = "contains_fallback"           # 包含 fallback 技能
    EXECUTION_FAILED = "execution_failed"             # 执行失败
    MISSING_REQUIRED_PARAMS = "missing_required_params"  # 缺少必需参数
    NOT_TEMPLATEABLE = "not_templateable"             # 不可模板化
    SCHEMA_INCOMPLETE = "schema_incomplete"           # schema 不完整
    LOW_SUCCESS_RATE = "low_success_rate"             # 成功率过低
    UNSTABLE_PLAN = "unstable_plan"                   # 不稳定的计划
    NON_CACHEABLE_SKILL = "non_cacheable_skill"       # 包含不可缓存的技能
    GUI_AUTOMATION = "gui_automation"                 # GUI/桌面自动化
    DYNAMIC_CODE = "dynamic_code"                     # 动态代码执行
    UNSTABLE_NETWORK = "unstable_network"             # 不稳定网络依赖
    PARAMS_INFERRED = "params_inferred"               # 参数是推断出来的
    UNKNOWN_PARAMS = "unknown_params"                 # 包含未知参数字段
    ARTIFACT_DEPENDENCY = "artifact_dependency"       # 依赖 artifact 残留
    OUTPUT_TOO_LONG = "output_too_long"               # 输出内容过长（不可复用）


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class StepSkeleton:
    """
    步骤骨架（模板）：只保留结构，不保留具体参数值
    """
    id: str
    order: int
    skill_name: str
    param_schema: Dict[str, str]  # 参数名 -> 参数类型（如 "filename": "str", "count": "int"）
    depends_on: List[str] = field(default_factory=list)
    description: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "order": self.order,
            "skill_name": self.skill_name,
            "param_schema": self.param_schema,
            "depends_on": self.depends_on,
            "description": self.description
        }
    
    @classmethod
    def from_step(cls, step: "Step") -> StepSkeleton:
        """从 Step 提取 skeleton"""
        param_schema = {}
        for key, value in step.params.items():
            if isinstance(value, str):
                param_schema[key] = "str"
            elif isinstance(value, bool):
                param_schema[key] = "bool"
            elif isinstance(value, int):
                param_schema[key] = "int"
            elif isinstance(value, float):
                param_schema[key] = "float"
            elif isinstance(value, (list, tuple)):
                param_schema[key] = "list"
            elif isinstance(value, dict):
                param_schema[key] = "dict"
            else:
                param_schema[key] = "any"
        
        return cls(
            id=step.id,
            order=step.order,
            skill_name=step.skill_name,
            param_schema=param_schema,
            depends_on=step.depends_on,
            description=step.description
        )


@dataclass
class QualityMetrics:
    """缓存质量指标（用于淘汰决策）"""
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    last_success_time: Optional[float] = None
    last_failure_time: Optional[float] = None
    
    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0
    
    @property
    def is_stable(self) -> bool:
        """是否稳定（连续失败少于3次，且成功率>50%）"""
        return self.consecutive_failures < 3 and self.success_rate >= 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "consecutive_failures": self.consecutive_failures,
            "last_success_time": self.last_success_time,
            "last_failure_time": self.last_failure_time,
            "success_rate": self.success_rate
        }


@dataclass
class PlanTemplate:
    """
    计划模板（缓存对象的"正确形态"）
    
    设计目标：
    - 缓存"结构模板"，不缓存"具体参数"
    - 可复用、可实例化、可验证
    """
    plan_id: str                              # 唯一标识
    cache_key: str                            # 缓存键（用于命中）
    intent_type: str                          # 意图类型
    domain: str                               # 领域
    goal_signature: str                       # 规范化后的 goal 特征
    step_skeletons: List[StepSkeleton]        # 步骤骨架序列
    
    # 元数据
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    hit_count: int = 0
    
    # 质量指标
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    
    # TTL
    ttl_seconds: int = 3600  # 默认1小时
    
    def is_expired(self, now: float = None) -> bool:
        """是否过期"""
        now = now or time.time()
        return (now - self.created_at) > self.ttl_seconds
    
    def record_hit(self) -> None:
        """记录命中"""
        self.hit_count += 1
        self.last_used = time.time()
    
    def record_success(self) -> None:
        """记录执行成功"""
        self.quality.success_count += 1
        self.quality.consecutive_failures = 0
        self.quality.last_success_time = time.time()
    
    def record_failure(self) -> None:
        """记录执行失败"""
        self.quality.failure_count += 1
        self.quality.consecutive_failures += 1
        self.quality.last_failure_time = time.time()
    
    def should_evict(self) -> bool:
        """是否应该驱逐"""
        # 连续失败3次以上
        if self.quality.consecutive_failures >= 3:
            return True
        # 成功率低于30%且尝试次数>5
        total_attempts = self.quality.success_count + self.quality.failure_count
        if total_attempts >= 5 and self.quality.success_rate < 0.3:
            return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "cache_key": self.cache_key,
            "intent_type": self.intent_type,
            "domain": self.domain,
            "goal_signature": self.goal_signature,
            "step_skeletons": [s.to_dict() for s in self.step_skeletons],
            "created_at": self.created_at,
            "last_used": self.last_used,
            "hit_count": self.hit_count,
            "quality": self.quality.to_dict(),
            "ttl_seconds": self.ttl_seconds
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanTemplate:
        quality_data = data.get("quality", {})
        quality = QualityMetrics(
            success_count=quality_data.get("success_count", 0),
            failure_count=quality_data.get("failure_count", 0),
            consecutive_failures=quality_data.get("consecutive_failures", 0),
            last_success_time=quality_data.get("last_success_time"),
            last_failure_time=quality_data.get("last_failure_time")
        )
        
        skeletons = [
            StepSkeleton(
                id=s["id"],
                order=s["order"],
                skill_name=s["skill_name"],
                param_schema=s["param_schema"],
                depends_on=s.get("depends_on", []),
                description=s.get("description")
            )
            for s in data.get("step_skeletons", [])
        ]
        
        return cls(
            plan_id=data["plan_id"],
            cache_key=data["cache_key"],
            intent_type=data["intent_type"],
            domain=data["domain"],
            goal_signature=data["goal_signature"],
            step_skeletons=skeletons,
            created_at=data.get("created_at", time.time()),
            last_used=data.get("last_used", time.time()),
            hit_count=data.get("hit_count", 0),
            quality=quality,
            ttl_seconds=data.get("ttl_seconds", 3600)
        )


# ============================================================================
# 缓存键生成器
# ============================================================================

class CacheKeyGenerator:
    """
    统一的缓存键生成器
    
    策略：
    1. goal 规范化：去掉路径/数字/日期/随机 ID，保留动作与对象类别
    2. params 只保留"类型模式 + 关键槽位名"
    3. 两级 key：
       - template_key：用于复用 plan 结构
       - instance_key（可选）：用于短期复用"同一参数的完全任务"
    """
    
    @staticmethod
    def normalize_goal(goal: str) -> str:
        """
        规范化 goal
        
        示例：
        - "创建文件 test123.txt" → "创建文件 <file>"
        - "读取 /path/to/data.xlsx 的第一行" → "读取 <path> 的第一行"
        - "发送邮件给 user@example.com" → "发送邮件给 <email>"
        """
        normalized = goal
        
        # 1. 替换文件路径（绝对路径、相对路径）
        normalized = re.sub(r'[A-Za-z]:[/\\][^\s]+', '<path>', normalized)
        normalized = re.sub(r'\.{0,2}/[^\s]+', '<path>', normalized)
        
        # 2. 替换文件名（带扩展名）
        normalized = re.sub(r'\b[\w\-]+\.(txt|pdf|xlsx?|docx?|csv|json|xml|png|jpg|jpeg|gif|py|js|html|css)\b', '<file>', normalized)
        
        # 3. 替换数字（但保留"第一"、"第二"等序数词）
        normalized = re.sub(r'\b\d+\b', '<num>', normalized)
        
        # 4. 替换日期时间
        normalized = re.sub(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?', '<date>', normalized)
        normalized = re.sub(r'\d{1,2}:\d{2}(:\d{2})?', '<time>', normalized)
        
        # 5. 替换 email
        normalized = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', '<email>', normalized)
        
        # 6. 替换 URL
        normalized = re.sub(r'https?://[^\s]+', '<url>', normalized)
        
        # 7. 替换 UUID
        normalized = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '<uuid>', normalized)
        
        return normalized.strip()
    
    @staticmethod
    def extract_param_pattern(params: Dict[str, Any]) -> Dict[str, str]:
        """
        提取参数模式（类型 + 槽位名）
        
        示例：
        - {"filename": "test.txt", "content": "hello"} 
          → {"filename": "str", "content": "str"}
        """
        pattern = {}
        for key, value in params.items():
            if isinstance(value, str):
                pattern[key] = "str"
            elif isinstance(value, bool):
                pattern[key] = "bool"
            elif isinstance(value, int):
                pattern[key] = "int"
            elif isinstance(value, float):
                pattern[key] = "float"
            elif isinstance(value, (list, tuple)):
                pattern[key] = "list"
            elif isinstance(value, dict):
                pattern[key] = "dict"
            else:
                pattern[key] = "any"
        return pattern
    
    @staticmethod
    def generate_template_key(
        intent_type: str,
        domain: str,
        goal: str,
        params: Dict[str, Any]
    ) -> str:
        """
        生成模板键（用于复用 plan 结构）
        
        Args:
            intent_type: 意图类型
            domain: 领域
            goal: 任务目标
            params: 参数
        
        Returns:
            template_key: 如 "action_file_abc123"
        """
        # 规范化 goal
        normalized_goal = CacheKeyGenerator.normalize_goal(goal)
        
        # 提取参数模式
        param_pattern = CacheKeyGenerator.extract_param_pattern(params)
        
        # 生成哈希
        cache_data = {
            "intent_type": intent_type,
            "domain": str(domain),
            "goal_signature": normalized_goal,
            "param_pattern": param_pattern
        }
        cache_str = json.dumps(cache_data, sort_keys=True, ensure_ascii=False)
        cache_hash = hashlib.md5(cache_str.encode('utf-8')).hexdigest()[:12]
        
        return f"{intent_type}_{domain}_{cache_hash}"
