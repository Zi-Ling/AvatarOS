"""
config.py — EvolutionConfig 配置中心

所有演化运行时的阈值和开关集中管理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class EvolutionConfig:
    """
    演化配置中心。所有阈值和开关集中管理。
    """

    # TraceCollector 配置
    large_field_threshold_bytes: int = 10240          # 大字段外置引用阈值（默认 10KB）
    artifact_size_threshold_bytes: int = 1048576      # ArtifactSnapshot 内联阈值（默认 1MB）
    artifact_type_thresholds: Dict[str, int] = field( # 按 artifact_type 配置不同阈值
        default_factory=lambda: {}
    )

    # ReflectionGating 配置
    cost_anomaly_multiplier: float = 2.0              # 成本异常倍数（相对中位数）
    cost_baseline_max_samples: int = 100              # 成本基线保留的最近样本数

    # LearningCandidate 配置
    default_confidence_threshold: float = 0.6         # 默认置信度阈值
    confidence_thresholds_by_type: Dict[str, float] = field(
        default_factory=lambda: {
            "planner_rule": 0.6,
            "policy_hint": 0.7,                       # policy 风险更高，阈值更高
            "skill_score": 0.5,
            "workflow_template": 0.7,
            "memory_fact": 0.6,
        }
    )

    # ReflectionEngine 配置
    small_model_confidence_threshold: float = 0.4     # 小模型 confidence 低于此值时升级到大模型
    reflection_max_retries: int = 1

    # MemoryManager 注入配置
    max_memory_injection_count: int = 10              # Planner 每次最多注入记忆条数
    max_memory_injection_length: int = 4096           # Planner 每次最多注入记忆总长度（字符）

    # 离线学习配置
    offline_mode_enabled: bool = True                 # 是否启用离线学习模式
    offline_batch_size: int = 10                      # 离线批处理每批 trace 数量

    # Shadow 期配置
    shadow_period_hours: float = 24.0                  # shadow 候选观察期（小时）

    # 冷启动配置
    baseline_dir: str = "evolution_baselines"          # 基线文件目录

    def get_confidence_threshold(self, candidate_type: str) -> float:
        """获取指定 candidate type 的置信度阈值。"""
        return self.confidence_thresholds_by_type.get(
            candidate_type, self.default_confidence_threshold
        )
