"""
计划缓存模块

提供智能的计划缓存机制，自动判定哪些计划可复用、哪些不可复用。

主要组件：
- PlanCache: 主缓存管理器
- PlanValidator: 缓存策略验证器
- PlanTemplate: 缓存模板
- CacheKeyGenerator: 缓存键生成器

使用示例：

```python
from app.avatar.runtime.cache import get_plan_cache, PlanCache

# 获取全局缓存实例
cache = get_plan_cache(memory_manager)

# 查询缓存
template = cache.get(intent_type, domain, goal, params)

# 写入缓存（执行成功后）
cache.put(task, resolved_inputs, intent_type, domain)

# 报告执行结果
cache.report_success(cache_key)  # 或 cache.report_failure(cache_key)
```
"""
from .plan_cache import PlanCache, get_plan_cache
from .models import (
    CacheRejectReason,
    StepSkeleton,
    QualityMetrics,
    PlanTemplate,
    CacheKeyGenerator
)
from .validator import PlanValidator

__all__ = [
    "PlanCache",
    "get_plan_cache",
    "PlanValidator",
    "CacheRejectReason",
    "StepSkeleton",
    "QualityMetrics",
    "PlanTemplate",
    "CacheKeyGenerator",
]
