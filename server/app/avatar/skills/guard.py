from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pathlib import Path
import re

class SkillGuard(ABC):
    """
    Guardrail interface for validating skill execution BEFORE it happens.
    
    Philosophy V2:
    - No content inspection (no regex for "bad words")
    - No type validation (handled by Pydantic)
    - Focus on SERIOUS security violations:
      1. Path traversal (must stay in workspace)
      2. Dangerous system commands (no os.system)
      3. Critical deletions
    """
    def check(self, skill_name: str, params: Dict[str, Any]) -> bool:
        """Legacy interface: returns True if allowed."""
        return self.validate(skill_name, params) is None

    @abstractmethod
    def validate(self, skill_name: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Check if the skill execution is safe/valid.
        Returns:
            None: If check passes.
            str: Error message if check fails.
        """
        pass

class AllowAllSkillGuard(SkillGuard):
    def validate(self, skill_name: str, params: Dict[str, Any]) -> Optional[str]:
        return None

class PolicySkillGuard(SkillGuard):
    """
    A simplified guard that enforces HARD security boundaries.
    """
    
    # Dangerous modules/commands blacklist for python.run
    DANGEROUS_PATTERNS = [
        r"os\.system\(", 
        r"subprocess\.", 
        r"shutil\.rmtree\(",
        r"__import__\(",
        r"eval\(",
        r"exec\("
    ]

    def validate(self, skill_name: str, params: Dict[str, Any]) -> Optional[str]:
        # Debug log
        # logger.debug(f"SkillGuard: validating {skill_name} with params {params}")
        
        # 1. Path Safety Check (All file skills)
        if skill_name.startswith("file.") or skill_name.startswith("directory.") or \
           skill_name.startswith("csv.") or skill_name.startswith("json.") or \
           skill_name.startswith("word.") or skill_name.startswith("excel."):
            
            error = self._check_path_safety(params)
            if error: return error

        # 2. Python Code Safety Check
        if skill_name == "python.run":
            code = params.get("code", "")
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, code):
                    return f"Security Violation: Forbidden code pattern detected: {pattern}"

        return None

    def _check_path_safety(self, params: Dict[str, Any]) -> Optional[str]:
        """
        Ensure paths do not traverse outside workspace using '..'
        Note: We don't check absolute paths here because ctx.resolve_path handles base_path enforcement.
        We only check for obvious '..' malicious intent in the parameter string itself.
        """
        for key in ["relative_path", "path", "src", "dst"]:
            val = params.get(key)
            if isinstance(val, str):
                # Basic directory traversal check
                if ".." in val:
                     # Allow ".." only if it doesn't look like traversal (rough heuristic)
                     # But safer to just block explicit traversal attempts
                     if "/../" in val or "\\..\\" in val or val.startswith("../") or val.startswith("..\\"):
                         return f"Security Violation: Path traversal ('..') is not allowed in '{val}'"
        return None
