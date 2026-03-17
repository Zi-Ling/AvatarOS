"""
cold_start.py — 冷启动基线加载器

加载 GoldenRules、PolicyBaseline、WorkflowSeed、SkillPrior、BenchmarkSet。
缺失文件使用内置默认值，不阻塞启动。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.avatar.evolution.config import EvolutionConfig
from app.avatar.evolution.models import EvolutionVersion

logger = logging.getLogger(__name__)

# 内置默认基线
_DEFAULT_GOLDEN_RULES: List[dict] = [
    {"rule": "prefer_existing_workflow", "description": "优先复用已有工作流模板"},
    {"rule": "verify_before_commit", "description": "提交前必须验证"},
]
_DEFAULT_POLICY_BASELINE: List[dict] = [
    {"policy": "no_direct_code_modify", "description": "禁止直接修改生产代码"},
]
_DEFAULT_WORKFLOW_SEEDS: List[dict] = []
_DEFAULT_SKILL_PRIORS: List[dict] = []
_DEFAULT_BENCHMARK_SET: List[dict] = []


class ColdStartLoader:
    """
    冷启动基线加载。
    缺失文件使用内置默认值，记录警告日志，不阻塞系统启动。
    """

    def __init__(self, baseline_dir: Path, config: EvolutionConfig) -> None:
        self._baseline_dir = baseline_dir
        self._config = config

    def load_all(self) -> EvolutionVersion:
        """
        加载所有基线，返回 v0 版本记录。
        缺失文件记录警告日志并使用内置默认值。
        """
        loaded: List[str] = []
        missing: List[str] = []

        baselines = {
            "golden_rules": self.load_golden_rules,
            "policy_baseline": self.load_policy_baseline,
            "workflow_seeds": self.load_workflow_seeds,
            "skill_priors": self.load_skill_priors,
            "benchmark_set": self.load_benchmark_set,
        }

        results: Dict[str, Any] = {}
        for name, loader in baselines.items():
            data = loader()
            results[name] = data
            file_path = self._baseline_dir / f"{name}.json"
            if file_path.exists():
                loaded.append(name)
            else:
                missing.append(name)

        version = EvolutionVersion(
            version_id=str(uuid.uuid4()),
            version_number=0,
            timestamp=datetime.now(timezone.utc),
            changes=[f"cold_start_v0: loaded={loaded}, missing={missing}"],
        )

        logger.info(
            f"[ColdStartLoader] v0 loaded: {loaded}, missing (using defaults): {missing}"
        )
        return version

    def load_golden_rules(self) -> List[dict]:
        return self._load_file("golden_rules.json", _DEFAULT_GOLDEN_RULES)

    def load_policy_baseline(self) -> List[dict]:
        return self._load_file("policy_baseline.json", _DEFAULT_POLICY_BASELINE)

    def load_workflow_seeds(self) -> List[dict]:
        return self._load_file("workflow_seeds.json", _DEFAULT_WORKFLOW_SEEDS)

    def load_skill_priors(self) -> List[dict]:
        return self._load_file("skill_priors.json", _DEFAULT_SKILL_PRIORS)

    def load_benchmark_set(self) -> List[dict]:
        return self._load_file("benchmark_set.json", _DEFAULT_BENCHMARK_SET)

    def _load_file(self, filename: str, default: List[dict]) -> List[dict]:
        """加载单个基线文件，失败时返回默认值。"""
        file_path = self._baseline_dir / filename
        if not file_path.exists():
            logger.warning(f"[ColdStartLoader] {filename} not found, using defaults")
            return list(default)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            logger.error(f"[ColdStartLoader] {filename} is not a list, using defaults")
            return list(default)
        except Exception as exc:
            logger.error(f"[ColdStartLoader] Failed to load {filename}: {exc}, using defaults")
            return list(default)
