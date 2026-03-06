from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any, Dict


@dataclass
class SkillContext:
    """
    Execution context provided to every skill.

    Responsibilities:
    - Describe execution environment (workspace, dry-run, runtime bindings)
    - Provide *authoritative* path resolution
    - Bridge artifact registration to runtime
    """

    # =========================
    # Execution Environment
    # =========================

    # Root workspace for all relative paths (REQUIRED for file skills)
    base_path: Optional[Path] = None

    # Dry-run mode (no real side effects)
    dry_run: bool = False

    # Optional runtime integrations
    memory_manager: Optional[Any] = None
    learning_manager: Optional[Any] = None
    execution_context: Optional[Any] = None  # Runtime ExecutionContext

    # Free-form extension space (avoid abusing this)
    extra: Dict[str, Any] = field(default_factory=dict)

    # =========================
    # Path Resolution
    # =========================

    def resolve_path(self, path: str) -> Path:
        """
        Resolve a path in a strictly controlled way.

        Rules:
        1. Absolute paths are respected as-is
        2. Relative paths MUST be bound to base_path
        3. base_path is REQUIRED for relative paths
        4. No cwd guessing, no implicit resolve()

        This keeps execution deterministic and safe.
        """
        if not path:
            raise ValueError("resolve_path: empty path provided")

        p = Path(path)

        # Absolute path → trust caller
        if p.is_absolute():
            return p

        # Relative path → must bind to base_path
        if not self.base_path:
            raise RuntimeError(
                f"Relative path '{path}' cannot be resolved: base_path is not set"
            )

        return (self.base_path / p)

    # =========================
    # Artifact Registration
    # =========================

    def register_artifact(
        self,
        artifact_type: str,
        uri: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Manually register an artifact with the runtime.

        This is an *imperative escape hatch*.
        Prefer declarative artifact registration via SkillSpec whenever possible.

        Args:
            artifact_type:
                e.g. "file:text", "document:word", "image:png"
            uri:
                Absolute or workspace-relative path
            metadata:
                Optional structured metadata
        """
        if not self.execution_context:
            import logging
            logging.getLogger(__name__).warning(
                "register_artifact skipped: execution_context is None"
            )
            return

        artifacts = getattr(self.execution_context, "artifacts", None)
        if not artifacts:
            import logging
            logging.getLogger(__name__).warning(
                "register_artifact skipped: execution_context has no 'artifacts'"
            )
            return

        artifacts.add(
            type=artifact_type,
            uri=uri,
            meta=metadata or {}
        )

    # =========================
    # Serialization Support (for ProcessExecutor)
    # =========================

    def __getstate__(self):
        """
        自定义序列化：排除不可序列化的对象
        
        ProcessExecutor 需要通过 pickle 传递 SkillContext 到子进程。
        我们只保留可序列化的字段（base_path, dry_run, extra）。
        """
        state = {
            'base_path': self.base_path,
            'dry_run': self.dry_run,
            'extra': self.extra,
            # 不序列化：memory_manager, learning_manager, execution_context
        }
        return state

    def __setstate__(self, state):
        """
        自定义反序列化：恢复可序列化的字段
        
        不可序列化的字段（memory_manager 等）在子进程中设置为 None。
        这是安全的，因为子进程中的 Skill 不应该依赖这些运行时对象。
        """
        self.base_path = state.get('base_path')
        self.dry_run = state.get('dry_run', False)
        self.extra = state.get('extra', {})
        # 不可序列化的字段设置为 None
        self.memory_manager = None
        self.learning_manager = None
        self.execution_context = None
