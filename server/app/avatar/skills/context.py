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
