"""
DurableStateConfig — 持久化状态机灰度控制配置

通过环境变量或配置文件控制新旧路径切换，支持双写和回退。
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DurableStateConfig:
    """持久化状态机灰度配置"""

    # 总开关：是否启用 durable 路径
    enabled: bool = False

    # 最小任务持续时间（秒）：低于此阈值的任务不走 durable 路径
    min_task_duration_s: int = 30

    # 双写模式：同时写入旧路径和新路径（用于验证数据一致性）
    dual_write: bool = False

    # 心跳间隔（秒）
    heartbeat_interval_s: int = 30

    # Lease 超时（秒）
    lease_timeout_s: int = 90

    # Checkpoint 间隔（步数）
    checkpoint_interval: int = 5

    # 启动时自动恢复扫描
    recovery_scan_on_startup: bool = True

    # Effect Ledger 启用
    effect_ledger_enabled: bool = True

    @staticmethod
    def from_env() -> 'DurableStateConfig':
        """从环境变量加载配置。"""
        cfg = DurableStateConfig(
            enabled=os.getenv("DURABLE_STATE_ENABLED", "false").lower() == "true",
            min_task_duration_s=int(os.getenv("DURABLE_MIN_TASK_DURATION_S", "30")),
            dual_write=os.getenv("DURABLE_DUAL_WRITE", "false").lower() == "true",
            heartbeat_interval_s=int(os.getenv("DURABLE_HEARTBEAT_INTERVAL_S", "30")),
            lease_timeout_s=int(os.getenv("DURABLE_LEASE_TIMEOUT_S", "90")),
            checkpoint_interval=int(os.getenv("DURABLE_CHECKPOINT_INTERVAL", "5")),
            recovery_scan_on_startup=os.getenv("DURABLE_RECOVERY_SCAN", "true").lower() == "true",
            effect_ledger_enabled=os.getenv("DURABLE_EFFECT_LEDGER", "true").lower() == "true",
        )
        if cfg.enabled:
            logger.info(
                f"[DurableStateConfig] ENABLED — heartbeat={cfg.heartbeat_interval_s}s, "
                f"lease={cfg.lease_timeout_s}s, dual_write={cfg.dual_write}"
            )
        return cfg


# 全局单例
_config: DurableStateConfig | None = None


def get_durable_config() -> DurableStateConfig:
    """获取灰度配置单例。"""
    global _config
    if _config is None:
        _config = DurableStateConfig.from_env()
    return _config
