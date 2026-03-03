"""
StepVerifier — Post-execution verification layer.

Detects "success but wrong result" scenarios that are common in:
- Web automation (clicked wrong element, page didn't load correctly)
- File operations (file created but empty, wrong path)

Design:
- Lightweight checks, no LLM calls
- Returns (is_valid, reason) — if invalid, step is marked FAILED
- Skill-specific verifiers registered by category prefix
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Verification outcome."""
    valid: bool
    reason: str = ""


class StepVerifier:
    """
    Post-execution step verifier.
    
    Checks that a "successful" step actually produced the expected result.
    Called after StepExecutor marks a step as SUCCESS.
    """

    @staticmethod
    def verify(skill_name: str, params: Dict[str, Any], output: Any) -> VerificationResult:
        """
        Verify step output based on skill category.
        
        Args:
            skill_name: The skill that was executed (e.g. "browser.open")
            params: The resolved parameters that were passed to the skill
            output: The skill's output (dict or SkillOutput)
            
        Returns:
            VerificationResult with valid=True if output looks correct
        """
        if not output:
            return VerificationResult(valid=False, reason="Output is None/empty")

        out = output if isinstance(output, dict) else (
            output.dict() if hasattr(output, "dict") else {}
        )

        # Route to category-specific verifier
        prefix = skill_name.split(".")[0] if "." in skill_name else skill_name
        
        verifier_map = {
            "browser": StepVerifier._verify_web,
            "web": StepVerifier._verify_web,
            "excel": StepVerifier._verify_file,
            "file": StepVerifier._verify_file,
            "word": StepVerifier._verify_file,
            "pdf": StepVerifier._verify_file,
            "csv": StepVerifier._verify_file,
            "json": StepVerifier._verify_file,
            "directory": StepVerifier._verify_directory,
            "archive": StepVerifier._verify_file,
        }

        verifier_fn = verifier_map.get(prefix)
        if verifier_fn:
            return verifier_fn(skill_name, params, out)

        # No specific verifier — trust the skill's own success flag
        return VerificationResult(valid=True)

    # ---- Web skill verifiers ----

    @staticmethod
    def _verify_web(skill_name: str, params: Dict[str, Any], out: Dict[str, Any]) -> VerificationResult:
        """Verify web/browser skill outputs."""
        
        # browser.open / web.open_page: check current_url is not empty
        if "open" in skill_name:
            current_url = out.get("current_url", "")
            if not current_url:
                return VerificationResult(valid=False, reason="Page opened but current_url is empty")
            
            # Check for common error page indicators in the URL
            error_indicators = ["error", "404", "500", "blocked", "captcha"]
            url_lower = current_url.lower()
            for indicator in error_indicators:
                if indicator in url_lower and indicator not in params.get("url", "").lower():
                    return VerificationResult(
                        valid=False,
                        reason=f"Page URL contains '{indicator}': {current_url}"
                    )

        # browser.click: basic check — output message shouldn't indicate failure
        if "click" in skill_name:
            msg = out.get("message", "")
            if "not found" in msg.lower() or "timeout" in msg.lower():
                return VerificationResult(valid=False, reason=f"Click reported issue: {msg}")

        # browser.fill: verify the filled value matches
        if "fill" in skill_name:
            msg = out.get("message", "")
            if "mismatch" in msg.lower() or "verification failed" in msg.lower():
                return VerificationResult(valid=False, reason=f"Fill verification failed: {msg}")

        return VerificationResult(valid=True)

    # ---- File skill verifiers ----

    @staticmethod
    def _verify_file(skill_name: str, params: Dict[str, Any], out: Dict[str, Any]) -> VerificationResult:
        """Verify file-producing skill outputs."""
        
        # Only verify write/create operations, not reads
        if "read" in skill_name:
            return VerificationResult(valid=True)

        # Check output path exists and is non-empty
        path = out.get("path") or out.get("output_path") or out.get("file_path")
        if not path:
            return VerificationResult(valid=True)  # No path in output, can't verify

        if not os.path.exists(path):
            return VerificationResult(valid=False, reason=f"Output file not found: {path}")

        file_size = os.path.getsize(path)
        if file_size == 0:
            return VerificationResult(valid=False, reason=f"Output file is empty (0 bytes): {path}")

        return VerificationResult(valid=True)

    # ---- Directory skill verifiers ----

    @staticmethod
    def _verify_directory(skill_name: str, params: Dict[str, Any], out: Dict[str, Any]) -> VerificationResult:
        """Verify directory skill outputs."""
        path = out.get("path") or out.get("dst")
        if not path:
            return VerificationResult(valid=True)

        if "create" in skill_name or "copy" in skill_name or "move" in skill_name:
            if not os.path.exists(path):
                return VerificationResult(valid=False, reason=f"Directory not found: {path}")

        return VerificationResult(valid=True)
