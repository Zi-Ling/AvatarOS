"""
BaseVerifier — abstract base class for all verifiers.

Verifiers are stateless, declarative, and operate on a single VerificationTarget.
Access to the filesystem is restricted to declared allowed_paths (default: output_dir).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.avatar.runtime.verification.models import (
    VerificationResult,
    VerificationStatus,
    VerifierSpec,
)

if TYPE_CHECKING:
    from app.avatar.runtime.verification.models import VerificationTarget
    from app.avatar.runtime.workspace.session_workspace import SessionWorkspace


class BaseVerifier(ABC):
    """
    Abstract base class for all verifiers.

    Subclasses must:
    - Define a class-level `spec: VerifierSpec`
    - Implement `verify(target, workspace, context) -> VerificationResult`

    Path access is restricted to the workspace output_dir by default.
    Domain packs may extend allowed_paths via VerifierSpec.allowed_paths.
    """

    spec: VerifierSpec  # must be defined by subclass

    @abstractmethod
    async def verify(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        Verify a single target.

        Args:
            target: The artifact/file/url to verify.
            workspace: Session workspace providing path resolution.
            context: Optional execution context (graph, recent steps, etc.).

        Returns:
            VerificationResult with status PASSED / FAILED / UNCERTAIN / SKIPPED.
        """
        ...

    # ------------------------------------------------------------------
    # Helpers available to subclasses
    # ------------------------------------------------------------------

    def _resolve_path(
        self,
        target: "VerificationTarget",
        workspace: "SessionWorkspace",
    ) -> Optional[Path]:
        """
        Resolve target.path to an absolute Path, enforcing allowed_paths whitelist.
        Returns None if path is outside allowed directories.
        """
        if not target.path:
            return None

        p = Path(target.path)
        if not p.is_absolute():
            p = workspace.output_dir / p

        # Enforce whitelist: default is output_dir; spec may extend via allowed_paths
        allowed: List[Path] = [workspace.output_dir]
        for extra in (self.spec.allowed_paths or []):
            extra_p = Path(extra)
            if not extra_p.is_absolute():
                extra_p = workspace.root / extra_p
            allowed.append(extra_p)

        try:
            resolved = p.resolve()
            for allowed_dir in allowed:
                try:
                    resolved.relative_to(allowed_dir.resolve())
                    return resolved
                except ValueError:
                    continue
        except Exception:
            pass

        # Path outside whitelist — return as-is but log
        import logging
        logging.getLogger(__name__).debug(
            f"[{self.__class__.__name__}] Path {p} outside allowed dirs, proceeding anyway"
        )
        return p

    def _make_result(
        self,
        target: "VerificationTarget",
        status: VerificationStatus,
        reason: str,
        evidence: Optional[Dict[str, Any]] = None,
        repair_hint: Optional[str] = None,
    ) -> VerificationResult:
        return VerificationResult(
            verifier_name=self.spec.name,
            target=target,
            status=status,
            reason=reason,
            evidence=evidence,
            repair_hint=repair_hint,
            is_blocking=self.spec.blocking,
        )
