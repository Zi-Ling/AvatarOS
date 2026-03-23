"""
Path sanitization mixin for GraphExecutor.

Handles replacing host machine absolute paths with container paths in
code strings and JSON values, preventing SyntaxError from unescaped
backslashes in Windows paths.

Extracted from graph_executor.py to keep the executor module focused on
core execution logic.
"""

from __future__ import annotations
from typing import Dict, Any, List
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PathSanitizerMixin:
    """Mixin providing path sanitization methods for GraphExecutor."""

    def _build_host_path_mappings(self) -> list:
        """
        Build (fwd, back, mount) tuples for host→container path replacement.
        Session workspace first (longer prefix must match first to avoid
        being swallowed by user workspace prefix).

        Shared by _sanitize_code_host_paths, _sanitize_json_value_host_paths,
        and any future path sanitization logic.
        """
        from app.avatar.runtime.workspace.session_workspace import (
            CONTAINER_WORKSPACE_PATH, CONTAINER_SESSION_PATH,
        )
        mappings: list = []

        # Session workspace → /session
        _effective_ws = getattr(self, "workspace", None)
        if _effective_ws is not None and hasattr(_effective_ws, "root"):
            session_root = str(Path(_effective_ws.root).resolve())
            session_fwd = session_root.replace("\\", "/").rstrip("/")
            session_back = session_root.replace("/", "\\").rstrip("\\")
            mappings.append((session_fwd, session_back, CONTAINER_SESSION_PATH))

        # User workspace → /workspace
        base_path = self._get_base_path()
        if base_path:
            workspace_root = str(Path(base_path).resolve())
            root_fwd = workspace_root.replace("\\", "/").rstrip("/")
            root_back = workspace_root.replace("/", "\\").rstrip("\\")
            mappings.append((root_fwd, root_back, CONTAINER_WORKSPACE_PATH))

        return mappings

    def _sanitize_json_value_host_paths(self, value: Any) -> Any:
        """
        Recursively replace host machine absolute paths in a JSON-serializable
        value with container paths.  Used to sanitize step output data BEFORE
        writing to /session/input/ JSON files.
        """
        import re as _re

        path_mappings = self._build_host_path_mappings()
        if not path_mappings:
            return value

        def _replace_in_str(s: str) -> str:
            result = s
            for fwd, back, mount in path_mappings:
                if fwd not in result and back not in result:
                    continue
                escaped_fwd = _re.escape(fwd)
                escaped_back = _re.escape(back)
                pattern = f"({escaped_fwd}|{escaped_back})[^\\s\"'\\)\\]]*"

                def _repl(m, _prefix_fwd=fwd, _mount=mount):
                    full = m.group(0)
                    normalized = full.replace("\\", "/")
                    if normalized.startswith(_prefix_fwd):
                        rel = normalized[len(_prefix_fwd):].lstrip("/")
                        return f"{_mount}/{rel}" if rel else _mount
                    return full

                result = _re.sub(pattern, _repl, result)
            return result

        def _walk(obj: Any) -> Any:
            if isinstance(obj, str):
                return _replace_in_str(obj)
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(item) for item in obj]
            return obj

        return _walk(value)

    def _sanitize_code_host_paths(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace host machine absolute paths in python.run code with container paths.
        Prevents SyntaxError from unescaped backslashes in Windows paths.
        """
        code = params.get("code", "")
        if not code:
            return params

        import re as _re

        path_mappings = self._build_host_path_mappings()
        if not path_mappings:
            return params

        changed = False
        new_code = code
        for fwd, back, mount in path_mappings:
            escaped_fwd = _re.escape(fwd)
            escaped_back = _re.escape(back)
            pattern = f"({escaped_fwd}|{escaped_back})[^\\s\"'\\)\\]]*"

            def _make_replacer(prefix_fwd, mount_path):
                def _replace(m):
                    full = m.group(0)
                    normalized = full.replace("\\", "/")
                    if normalized.startswith(prefix_fwd):
                        rel = normalized[len(prefix_fwd):].lstrip("/")
                        return f"{mount_path}/{rel}" if rel else mount_path
                    return full
                return _replace

            result = _re.sub(pattern, _make_replacer(fwd, mount), new_code)
            if result != new_code:
                changed = True
                new_code = result

        if changed:
            logger.debug("[GraphExecutor] Sanitized host paths in python.run code")
            return {**params, "code": new_code}
        return params

    @staticmethod
    def _replace_workspace_template_vars(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace LLM-generated template variables like {{workspace_path}}
        with the actual container mount path /workspace.

        LLMs sometimes emit {{workspace_path}} as a placeholder instead of
        using the literal /workspace path. This safety net catches those cases.
        """
        code = params.get("code", "")
        if not code or "{{" not in code:
            return params

        from app.avatar.runtime.workspace.session_workspace import CONTAINER_WORKSPACE_PATH

        import re as _re
        # Match {{workspace_path}}, {{ workspace_path }}, etc.
        new_code = _re.sub(
            r'\{\{\s*workspace_path\s*\}\}',
            CONTAINER_WORKSPACE_PATH,
            code,
        )
        if new_code != code:
            logger.debug("[GraphExecutor] Replaced {{workspace_path}} template variable with %s", CONTAINER_WORKSPACE_PATH)
            return {**params, "code": new_code}
        return params

    @staticmethod
    def _replace_template_vars_in_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replace {{workspace_path}} template variables in ALL string params
        (not just code). Handles paths in fs.write, fs.read, etc.
        """
        from app.avatar.runtime.workspace.session_workspace import CONTAINER_WORKSPACE_PATH
        import re as _re

        _pattern = _re.compile(r'\{\{\s*workspace_path\s*\}\}')
        changed = False
        new_params = {}
        for k, v in params.items():
            if isinstance(v, str) and "{{" in v:
                replaced = _pattern.sub(CONTAINER_WORKSPACE_PATH, v)
                if replaced != v:
                    changed = True
                    new_params[k] = replaced
                    continue
            new_params[k] = v

        if changed:
            logger.debug("[GraphExecutor] Replaced {{workspace_path}} in skill params")
            return new_params
        return params
