"""
计划缓存模块（v4 严格策略版）

核心改进：
1. 缓存时机：从"规划后立刻存"改为"执行后通过才存"
2. 缓存内容：存"计划模板（skeleton）"而非"完整参数"
3. 严格验证：PlanValidator 实现多层门槛缓存策略
4. 可观测性：命中/写入/拒绝原因都打点记录
5. 失败反馈：命中后执行失败会降权/驱逐缓存

文件结构（已拆分）：
- models.py: 数据模型（CacheRejectReason, StepSkeleton, QualityMetrics, PlanTemplate, CacheKeyGenerator）
- validator.py: 验证器（PlanValidator 及所有验证逻辑）
- plan_cache.py: 主缓存类（PlanCache 和全局单例）

缓存策略分级（v4 严格版）：
一、必须缓存（高复用 + 低上下文依赖）
   - 纯文件 I/O：file.write、file.read、file.copy、directory.create 等
   - 纯文本处理：text.replace、text.split、text.format 等
   - 纯数据读写：csv.read、json.write、excel.write_table 等

二、绝对不缓存（高风险 / 强环境依赖 / 不可复用）—— 一票否决
   - LLM 自由生成：llm.fallback、llm.chat、llm.generate
   - 动态代码执行：python.run、shell.execute
   - GUI/桌面自动化：computer.*、mouse.*、keyboard.*、screen.*
   - 不稳定网络：browser.*、http.*、web.scrape

三、有条件缓存（建议缓存，但要加硬门槛）
   - LLM 结构化小输出：llm.extract、llm.classify、llm.summarize_short
   - 文档操作：excel.write、word.write、pdf.create
   - 多步编排：读取 -> 处理 -> 写回

四、缓存门槛（硬门槛 - 触发任一条即拒绝）
   1. 未知字段：step.params 含未知字段（LLM 发明的参数名）
   2. artifact 依赖：引用"最近 artifact"但 goal/input 未显式提供
   3. 参数不可模板化：包含超长文本、UUID、时间戳、随机 token
   4. 成功率不足：连续失败 >= 3 次
   5. 步骤过多：>10 步
   7. 全是未知技能：所有技能都不在预定义列表中

职责边界：
- 不在 planner 写入缓存
- 由 runtime/executor 执行完成后调用 cache.put()
- cache.get() 由 runtime 或 planner 在规划前调用
- PlanValidator.validate() 负责所有缓存判定逻辑
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Any, List, TYPE_CHECKING

from .models import (
    CacheRejectReason,
    StepSkeleton,
    QualityMetrics,
    PlanTemplate,
    CacheKeyGenerator
)
from .validator import PlanValidator

if TYPE_CHECKING:
    from app.avatar.memory.manager import MemoryManager
    from app.avatar.planner.models import Task, Step

logger = logging.getLogger(__name__)


# ============================================================================
# 计划缓存管理器
# ============================================================================

class PlanCache:
    """
    计划缓存管理器（v2 重构版）
    
    核心原则：
    1. 只缓存"执行成功 + 通过验证"的计划模板
    2. 缓存"结构"而非"参数"
    3. 失败反馈驱动淘汰
    4. 可观测：命中/写入/拒绝都打点
    """
    
    def __init__(
        self,
        memory_manager: Optional[MemoryManager] = None,
        max_size: int = 100,
        ttl_seconds: int = 3600,
        enable_persist: bool = True
    ):
        """
        Args:
            memory_manager: MemoryManager 实例（用于持久化）
            max_size: 最大缓存数
            ttl_seconds: 缓存有效期（秒）
            enable_persist: 是否启用持久化
        """
        self._memory = memory_manager
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._enable_persist = enable_persist and (memory_manager is not None)
        
        # 本地索引（内存）
        self._templates: Dict[str, PlanTemplate] = {}
        
        # 统计
        self._stats = {
            "hit": 0,
            "miss": 0,
            "put_success": 0,
            "put_rejected": 0,
            "evicted": 0,
            "rejected_reasons": {}  # {reason: count}
        }
        
        # 加载已有缓存
        if self._enable_persist:
            self._load_from_storage()
            logger.info(f"✅ PlanCache initialized (persist=ON, loaded={len(self._templates)} templates)")
        else:
            logger.info(f"✅ PlanCache initialized (persist=OFF, memory-only)")
    
    # ========== 缓存命中 ========== #
    
    def get(
        self,
        intent_type: str,
        domain: str,
        goal: str,
        params: Dict[str, Any]
    ) -> Optional[PlanTemplate]:
        """
        获取缓存的计划模板
        
        Args:
            intent_type: 意图类型
            domain: 领域
            goal: 任务目标
            params: 参数
        
        Returns:
            PlanTemplate 或 None
        """
        # ✅ 硬防线：类型检查，避免参数顺序错误导致的 silent 爆炸
        if not isinstance(goal, str):
            logger.error(
                f"❌ PlanCache.get() type error: goal must be str, got {type(goal).__name__}\n"
                f"  intent_type={intent_type!r}, domain={domain!r}\n"
                f"  goal (wrong type)={goal!r}\n"
                f"  params={params!r}\n"
                f"  Hint: 调用参数顺序应为 get(intent_type, domain, goal, params)"
            )
            self._stats["miss"] += 1
            return None
        
        if not isinstance(params, dict):
            logger.error(
                f"❌ PlanCache.get() type error: params must be dict, got {type(params).__name__}\n"
                f"  intent_type={intent_type!r}, domain={domain!r}, goal={goal!r}\n"
                f"  params (wrong type)={params!r}\n"
                f"  Hint: 调用参数顺序应为 get(intent_type, domain, goal, params)"
            )
            self._stats["miss"] += 1
            return None
        
        cache_key = CacheKeyGenerator.generate_template_key(intent_type, domain, goal, params)
        
        template = self._templates.get(cache_key)
        
        if template is None:
            self._stats["miss"] += 1
            logger.debug(f"❌ PlanCache MISS: {cache_key}")
            return None
        
        # 检查是否过期
        if template.is_expired():
            logger.info(f"🕐 PlanCache expired: {cache_key}, evicting")
            self._evict(cache_key)
            self._stats["miss"] += 1
            return None
        
        # 检查是否应该驱逐（质量过低）
        if template.should_evict():
            logger.warning(
                f"🚫 PlanCache evicted due to low quality: {cache_key} "
                f"(success_rate={template.quality.success_rate:.1%}, "
                f"consecutive_failures={template.quality.consecutive_failures})"
            )
            self._evict(cache_key)
            self._stats["miss"] += 1
            self._stats["evicted"] += 1
            return None
        
        # 命中！
        template.record_hit()
        self._stats["hit"] += 1
        logger.info(
            f"✅ PlanCache HIT: {cache_key} "
            f"(hits={template.hit_count}, success_rate={template.quality.success_rate:.1%})"
        )
        
        # 更新持久化
        if self._enable_persist:
            self._save_to_storage(cache_key, template)
        
        return template
    
    # ========== 缓存写入 ========== #
    
    def put(
        self,
        task: "Task",
        resolved_inputs: Optional[Dict[str, Any]] = None,
        intent_type: str = "action",
        domain: str = "general"
    ) -> bool:
        """
        缓存计划（执行成功后才调用）
        
        Args:
            task: 执行完成的任务
            resolved_inputs: Intent 解析后的输入参数（不要用 task.metadata）
            intent_type: 意图类型
            domain: 领域
        
        Returns:
            bool: 是否成功写入
        """
        # 1. 验证是否可缓存
        is_valid, reject_reason, detail = PlanValidator.validate(task)
        
        if not is_valid:
            self._stats["put_rejected"] += 1
            if reject_reason:
                self._stats["rejected_reasons"][reject_reason.value] = \
                    self._stats["rejected_reasons"].get(reject_reason.value, 0) + 1
            
            logger.debug(
                f"🚫 PlanCache PUT rejected: {task.id} "
                f"(reason={reject_reason.value if reject_reason else 'unknown'}, detail={detail})"
            )
            return False
        
        # 2. 提取真实参数（从 step.params 聚合，不依赖 task.metadata）
        # 这样即使 task.metadata 为空，也能正确生成 cache_key
        actual_params = resolved_inputs if resolved_inputs is not None else {}
        if not actual_params:
            # 从 steps 中聚合参数类型模式
            actual_params = self._aggregate_params_from_steps(task.steps)
        
        # 3. 生成缓存键
        cache_key = CacheKeyGenerator.generate_template_key(
            intent_type, domain, task.goal, actual_params
        )
        
        # 4. 检查是否已存在（如果存在，更新质量指标）
        existing = self._templates.get(cache_key)
        if existing:
            existing.record_success()
            logger.info(
                f"✅ PlanCache updated: {cache_key} "
                f"(success_rate={existing.quality.success_rate:.1%})"
            )
            if self._enable_persist:
                self._save_to_storage(cache_key, existing)
            return True
        
        # 4. 创建新模板
        goal_signature = CacheKeyGenerator.normalize_goal(task.goal)
        step_skeletons = [StepSkeleton.from_step(s) for s in task.steps]
        
        template = PlanTemplate(
            plan_id=task.id,
            cache_key=cache_key,
            intent_type=intent_type,
            domain=domain,
            goal_signature=goal_signature,
            step_skeletons=step_skeletons,
            ttl_seconds=self._ttl_seconds
        )
        template.quality.success_count = 1  # 首次成功
        
        # 5. 检查容量，必要时驱逐最旧的
        if len(self._templates) >= self._max_size:
            oldest_key = min(
                self._templates.keys(),
                key=lambda k: self._templates[k].last_used
            )
            logger.info(f"🗑️ PlanCache evicted (capacity): {oldest_key}")
            self._evict(oldest_key)
            self._stats["evicted"] += 1
        
        # 6. 写入缓存
        self._templates[cache_key] = template
        self._stats["put_success"] += 1
        
        logger.info(
            f"💾 PlanCache PUT: {cache_key} "
            f"(steps={len(step_skeletons)}, goal='{goal_signature}')"
        )
        
        # 7. 持久化
        if self._enable_persist:
            self._save_to_storage(cache_key, template)
        
        return True
    
    # ========== 失败反馈 ========== #
    
    def report_failure(self, cache_key: str) -> None:
        """
        报告缓存命中后执行失败
        
        Args:
            cache_key: 缓存键
        """
        template = self._templates.get(cache_key)
        if template is None:
            return
        
        template.record_failure()
        
        logger.warning(
            f"❌ PlanCache failure reported: {cache_key} "
            f"(consecutive_failures={template.quality.consecutive_failures}, "
            f"success_rate={template.quality.success_rate:.1%})"
        )
        
        # 检查是否应该驱逐
        if template.should_evict():
            logger.error(
                f"🚫 PlanCache evicting due to failures: {cache_key} "
                f"(consecutive_failures={template.quality.consecutive_failures})"
            )
            self._evict(cache_key)
            self._stats["evicted"] += 1
        elif self._enable_persist:
            self._save_to_storage(cache_key, template)
    
    def report_success(self, cache_key: str) -> None:
        """
        报告缓存命中后执行成功
        
        Args:
            cache_key: 缓存键
        """
        template = self._templates.get(cache_key)
        if template is None:
            return
        
        template.record_success()
        
        logger.info(
            f"✅ PlanCache success reported: {cache_key} "
            f"(success_rate={template.quality.success_rate:.1%})"
        )
        
        if self._enable_persist:
            self._save_to_storage(cache_key, template)
    
    # ========== 缓存管理 ========== #
    
    def clear(self) -> None:
        """清空所有缓存"""
        if self._enable_persist and self._memory:
            # 删除持久化存储
            from app.avatar.memory.base import MemoryKind
            records = self._memory.query_records(
                MemoryKind.WORKING_STATE,
                prefix="runtime_cache:plan:",
                limit=1000
            )
            for rec in records:
                # TODO: 等 MemoryManager 支持 delete 方法
                pass
        
        self._templates.clear()
        logger.info("🧹 PlanCache cleared")
    
    def _evict(self, cache_key: str) -> None:
        """驱逐缓存"""
        if cache_key in self._templates:
            del self._templates[cache_key]
        
        # 删除持久化（TODO: 等 delete 方法）
        # if self._enable_persist and self._memory:
        #     self._memory.delete_working_state(f"runtime_cache:plan:{cache_key}")
    
    # ========== 模板实例化 ========== #
    
    def instantiate(
        self,
        template: PlanTemplate,
        resolved_inputs: Dict[str, Any],
        goal: str
    ) -> Optional[List["Step"]]:
        """
        将模板实例化为可执行的 steps
        
        Args:
            template: 缓存的计划模板
            resolved_inputs: Intent 解析后的输入参数
            goal: 当前任务目标
        
        Returns:
            List[Step] 或 None（缺少必要参数时）
        """
        from app.avatar.planner.models import Step, StepStatus
        
        steps = []
        missing_params = []
        
        for skeleton in template.step_skeletons:
            # 实例化参数
            params = {}
            for param_name, param_type in skeleton.param_schema.items():
                # 尝试从 resolved_inputs 中获取
                if param_name in resolved_inputs:
                    params[param_name] = resolved_inputs[param_name]
                else:
                    # 尝试从 goal 中推断（简单启发式）
                    inferred_value = self._infer_param_from_goal(param_name, param_type, goal)
                    if inferred_value is not None:
                        params[param_name] = inferred_value
                    else:
                        # 缺少必需参数
                        missing_params.append(f"{skeleton.skill_name}.{param_name}")
            
            if missing_params:
                logger.warning(
                    f"❌ PlanCache instantiation failed: missing params {missing_params} "
                    f"for template {template.cache_key}"
                )
                return None
            
            # 创建 Step
            step = Step(
                id=skeleton.id,
                order=skeleton.order,
                skill_name=skeleton.skill_name,
                params=params,
                status=StepStatus.PENDING,
                depends_on=skeleton.depends_on,
                description=skeleton.description
            )
            steps.append(step)
        
        logger.info(
            f"✅ PlanCache instantiated: {len(steps)} steps from template {template.cache_key}"
        )
        return steps
    
    def _infer_param_from_goal(
        self,
        param_name: str,
        param_type: str,
        goal: str
    ) -> Optional[Any]:
        """
        从 goal 中推断参数值（简单启发式）
        
        Args:
            param_name: 参数名
            param_type: 参数类型
            goal: 任务目标
        
        Returns:
            推断的值 或 None
        """
        import re
        
        # 文件名推断
        if param_name in ("filename", "file_path", "path"):
            # 提取文件名（带扩展名）
            match = re.search(r'\b([\w\-]+\.[\w]{2,5})\b', goal)
            if match:
                return match.group(1)
        
        # 内容推断（从引号中提取）
        if param_name in ("content", "text", "message"):
            # 提取引号内容
            match = re.search(r'["""\'](.*?)["""\']', goal)
            if match:
                return match.group(1)
        
        # 数字推断
        if param_name in ("count", "number", "amount") and param_type == "int":
            match = re.search(r'\b(\d+)\b', goal)
            if match:
                return int(match.group(1))
        
        return None
    
    def _aggregate_params_from_steps(self, steps: List["Step"]) -> Dict[str, Any]:
        """
        从 steps 中聚合参数（用于生成 cache_key）
        
        这是兜底方案：当 resolved_inputs 不可用时，从 step.params 聚合
        
        Args:
            steps: 步骤列表
        
        Returns:
            聚合的参数字典
        """
        aggregated = {}
        for step in steps:
            # 提取关键参数（文件名、路径、内容等）
            for key, value in step.params.items():
                # 只保留"有代表性"的参数
                if key in ("filename", "file_path", "path", "content", "text", "query", "prompt"):
                    if key not in aggregated:
                        aggregated[key] = value
        
        return aggregated
    
    # ========== 统计 ========== #
    
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_requests = self._stats["hit"] + self._stats["miss"]
        hit_rate = self._stats["hit"] / total_requests if total_requests > 0 else 0.0
        
        return {
            "size": len(self._templates),
            "max_size": self._max_size,
            "hit": self._stats["hit"],
            "miss": self._stats["miss"],
            "hit_rate": hit_rate,
            "put_success": self._stats["put_success"],
            "put_rejected": self._stats["put_rejected"],
            "evicted": self._stats["evicted"],
            "rejected_reasons": self._stats["rejected_reasons"],
            "persist_enabled": self._enable_persist,
            "templates": [
                {
                    "cache_key": t.cache_key,
                    "goal_signature": t.goal_signature,
                    "steps_count": len(t.step_skeletons),
                    "hit_count": t.hit_count,
                    "success_rate": t.quality.success_rate,
                    "age_seconds": time.time() - t.created_at
                }
                for t in self._templates.values()
            ]
        }
    
    # ========== 持久化 ========== #
    
    def _save_to_storage(self, cache_key: str, template: PlanTemplate) -> None:
        """保存到持久化存储"""
        if not self._memory:
            return
        
        try:
            storage_key = f"runtime_cache:plan:{cache_key}"
            self._memory.set_working_state(storage_key, template.to_dict())
        except Exception as e:
            logger.error(f"Failed to persist cache {cache_key}: {e}")
    
    def _load_from_storage(self) -> None:
        """从持久化存储加载"""
        if not self._memory:
            return
        
        try:
            from app.avatar.memory.base import MemoryKind
            records = self._memory.query_records(
                MemoryKind.WORKING_STATE,
                prefix="runtime_cache:plan:",
                limit=self._max_size
            )
            
            loaded_count = 0
            for rec in records:
                if rec.data:
                    try:
                        template = PlanTemplate.from_dict(rec.data)
                        
                        # 检查是否过期
                        if not template.is_expired():
                            self._templates[template.cache_key] = template
                            loaded_count += 1
                    except Exception as e:
                        logger.error(f"Failed to load cache template: {e}")
            
            logger.info(f"✅ Loaded {loaded_count} cache templates from storage")
        except Exception as e:
            logger.error(f"Failed to load cache from storage: {e}")


# ============================================================================
# 全局单例
# ============================================================================

_global_plan_cache: Optional[PlanCache] = None


def get_plan_cache(memory_manager: Optional[MemoryManager] = None) -> PlanCache:
    """
    获取全局计划缓存实例
    
    Args:
        memory_manager: MemoryManager 实例（首次调用时必需，用于持久化）
    
    Returns:
        PlanCache 实例
    """
    global _global_plan_cache
    
    if _global_plan_cache is None:
        if memory_manager is None:
            logger.warning("⚠️ PlanCache: No MemoryManager provided, using memory-only mode")
            _global_plan_cache = PlanCache(memory_manager=None, enable_persist=False)
        else:
            _global_plan_cache = PlanCache(memory_manager=memory_manager, enable_persist=True)
    
    return _global_plan_cache
