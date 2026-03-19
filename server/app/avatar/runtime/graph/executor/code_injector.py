"""
Code injection mixin for GraphExecutor.

Handles injecting upstream node outputs into python.run code as typed input
artifacts, plus the _output() helper and _save_binary() helper.

Extracted from graph_executor.py to keep the executor module focused on
core execution logic.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional, TYPE_CHECKING
import json
import logging
from pathlib import Path

if TYPE_CHECKING:
    from app.avatar.runtime.graph.context.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class CodeInjectorMixin:
    """Mixin providing code injection methods for GraphExecutor."""

    # ------------------------------------------------------------------
    # _output() 显式结构化输出通道
    # ------------------------------------------------------------------

    _OUTPUT_MARKER = "__OUTPUT__:"

    def _output_helper_code(self) -> str:
        """注入到每个 python.run 代码头部的辅助函数定义"""
        marker = self._OUTPUT_MARKER
        return (
            "import json as _json\n"
            "import os as _os\n"
            # ── subprocess 拦截 ──
            "import types as _types\n"
            "_mock_subprocess = _types.ModuleType('subprocess')\n"
            "def _blocked_subprocess(*a, **kw):\n"
            "    raise RuntimeError('subprocess is blocked in sandbox. Write your logic directly in python.run code.')\n"
            "_mock_subprocess.run = _blocked_subprocess\n"
            "_mock_subprocess.Popen = _blocked_subprocess\n"
            "_mock_subprocess.call = _blocked_subprocess\n"
            "_mock_subprocess.check_output = _blocked_subprocess\n"
            "_mock_subprocess.check_call = _blocked_subprocess\n"
            "import sys as _sys\n"
            "_sys.modules['subprocess'] = _mock_subprocess\n"
            "\n"
            f"def _output(value):\n"
            f"    print('{marker}' + _json.dumps(value, ensure_ascii=False, default=str))\n"
            "\n"
            "def _save_binary(path, hex_str):\n"
            "    \"\"\"\n"
            "    把 hex 字符串写成二进制文件。\n"
            "    始终写到 /workspace（Docker 沙箱挂载点）或 cwd（本地执行）下。\n"
            "    写完后通过 _output() 输出结构化对象 {\"__file__\": path}，供框架识别为文件产物。\n"
            "    \"\"\"\n"
            "    _clean = ''.join(hex_str.split())\n"
            "    _data = bytes.fromhex(_clean)\n"
            "    _ws = '/workspace' if _os.path.isdir('/workspace') else _os.getcwd()\n"
            "    if _os.path.isabs(path):\n"
            "        _abs = _os.path.join(_ws, _os.path.basename(path))\n"
            "    else:\n"
            "        _abs = _os.path.join(_ws, path)\n"
            "    _dir = _os.path.dirname(_abs)\n"
            "    if _dir:\n"
            "        _os.makedirs(_dir, exist_ok=True)\n"
            "    with open(_abs, 'wb') as _f:\n"
            "        _f.write(_data)\n"
            "    _output({'__file__': _abs, 'path': _abs})\n"
            "\n"
        )

    def _inject_output_helper(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """无上游输出时，仅注入 _output() helper"""
        original_code = params.get("code", "")
        if isinstance(original_code, list):
            original_code = "\n".join(str(line) for line in original_code)
        elif not isinstance(original_code, str):
            original_code = str(original_code)
        return {**params, "code": self._output_helper_code() + original_code}

    def _inject_node_outputs_repr_fallback(
        self,
        params: Dict[str, Any],
        context: 'ExecutionContext',
    ) -> Dict[str, Any]:
        """无 session workspace 时的兜底：repr 注入（旧行为）+ _output() helper"""
        all_outputs = context.get_all_node_outputs()

        lines: List[str] = []
        for node_id, outputs in all_outputs.items():
            if not outputs:
                continue
            value = (
                outputs.get("output")
                or outputs.get("content")
                or outputs.get("stdout")
                or outputs
            )
            if isinstance(value, dict) and not (set(value.keys()) - {"__artifacts__", "__artifact_paths__"}):
                continue
            lines.append(f"{node_id}_output = {repr(value)}")

        injected_prefix = "\n".join(lines) + "\n\n" if lines else ""
        original_code = params.get("code", "")
        if isinstance(original_code, list):
            original_code = "\n".join(str(line) for line in original_code)
        elif not isinstance(original_code, str):
            original_code = str(original_code)
        return {**params, "code": injected_prefix + self._output_helper_code() + original_code}

    def _inject_node_outputs_into_code(
        self,
        params: Dict[str, Any],
        context: 'ExecutionContext',
    ) -> Dict[str, Any]:
        """
        把上游节点输出写成 typed input artifacts，通过文件传入容器。

        每个上游输出写成一个 JSON 文件（对于 JSON 可序列化的值），
        或直接引用文件路径（对于文件产物）。
        同时写一个 manifest.json 列出所有输入。
        """
        from app.avatar.runtime.workspace.session_workspace import CONTAINER_WORKSPACE_PATH, CONTAINER_SESSION_PATH

        all_outputs = context.get_all_node_outputs()
        if not all_outputs:
            return self._inject_output_helper(params)

        # 优先从 context 取 workspace（session 隔离），fallback 到 self.workspace
        _effective_ws = getattr(context, "workspace", None) or self.workspace
        if _effective_ws is None:
            return self._inject_node_outputs_repr_fallback(params, context)

        workspace_root = str(Path(_effective_ws.root).resolve())
        inputs_dir = Path(_effective_ws.root) / "input"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        # 判断是否启用 dual-mount
        _user_ws = self._get_base_path()
        _has_user_ws = _user_ws is not None and str(_user_ws.resolve()) != workspace_root
        _input_mount = CONTAINER_SESSION_PATH if _has_user_ws else CONTAINER_WORKSPACE_PATH

        manifest: Dict[str, Any] = {}
        load_lines: List[str] = []

        for node_id, outputs in all_outputs.items():
            if not outputs:
                continue
            if isinstance(outputs, dict) and not (set(outputs.keys()) - {"__artifacts__", "__artifact_paths__"}):
                continue

            var_name = f"{node_id}_output"

            # 提取最有意义的值
            value = (
                outputs.get("output")
                or outputs.get("result")
                or outputs.get("content")
                or outputs.get("stdout")
                or outputs
            )

            # ── Record original type for manifest (debug/trace) ──
            # The raw value is written to JSON as-is so that downstream
            # python.run code can use step_N_output directly without
            # unwrapping.  Type metadata goes only into manifest.json.
            _original_type = type(value).__name__

            # 文件路径产物：直接映射容器内路径
            file_path_str = None
            if isinstance(outputs, dict):
                _out = outputs.get("output")
                if isinstance(_out, dict) and "__file__" in _out:
                    file_path_str = _out["__file__"]
                else:
                    file_path_str = outputs.get("file_path")
            if file_path_str:
                _fp = str(file_path_str)
                if _fp.startswith("/workspace/") or _fp.startswith("/workspace\\") or _fp.startswith("/session/"):
                    container_path = _fp.replace("\\", "/")
                else:
                    host_path = str(Path(_fp).resolve())
                    if host_path.startswith(workspace_root):
                        rel = host_path[len(workspace_root):].lstrip("/\\").replace("\\", "/")
                        container_path = f"{_input_mount}/{rel}"
                    else:
                        container_path = _fp.replace("\\", "/")
                manifest[var_name] = {
                    "format": "file_ref",
                    "container_path": container_path,
                    "type": type(value).__name__,
                }
                load_lines.append(f'{var_name} = "{container_path}"')
                continue

            # 结构化数据：序列化为 JSON 文件
            json_filename = f"{var_name}.json"
            json_path = inputs_dir / json_filename
            container_json_path = f"{_input_mount}/input/{json_filename}"

            try:
                sanitized_value = self._sanitize_json_value_host_paths(value)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(sanitized_value, f, ensure_ascii=False, default=str)
                manifest[var_name] = {
                    "format": "json",
                    "container_path": container_json_path,
                    "type": _original_type,
                }
                load_lines.append(
                    f'with open("{container_json_path}", encoding="utf-8") as _f:\n'
                    f'    {var_name} = json.load(_f)'
                )
            except Exception as e:
                logger.warning(f"[GraphExecutor] Failed to serialize {var_name} to JSON: {e}, falling back to repr")
                repr_val = repr(value)
                sanitized_repr = self._sanitize_json_value_host_paths(repr_val)
                if isinstance(sanitized_repr, str):
                    repr_val = sanitized_repr
                load_lines.append(f"{var_name} = {repr_val}")
                manifest[var_name] = {"format": "repr_fallback", "type": type(value).__name__}

        # 写 manifest.json
        manifest_path = inputs_dir / "manifest.json"
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[GraphExecutor] Failed to write manifest: {e}")

        if not load_lines:
            return self._inject_output_helper(params)

        injected_prefix = "import json\n" + "\n".join(load_lines) + "\n\n"
        original_code = params.get("code", "")
        if isinstance(original_code, list):
            original_code = "\n".join(str(line) for line in original_code)
        elif not isinstance(original_code, str):
            original_code = str(original_code)
        return {**params, "code": injected_prefix + self._output_helper_code() + original_code}
