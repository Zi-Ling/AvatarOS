# server/app/avatar/skills/core/python.py

from __future__ import annotations

import sys
import io
import traceback
import contextlib
import base64
import logging
import os
from typing import Any, Dict, Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SideEffect, SkillRiskLevel
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


class PythonRunInput(SkillInput):
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, description="Execution timeout in seconds")

class PythonRunOutput(SkillOutput):
    output: str = Field("", description="Primary output: stdout content")
    stdout: str = ""
    stderr: str = ""
    result: Optional[Any] = None
    variables: Dict[str, Any] = {}
    base64_image: Optional[str] = Field(None, description="Base64 encoded image if plot generated")
    dataframe_csv: Optional[str] = Field(None, description="CSV string if pandas dataframe detected")

@register_skill
class PythonRunSkill(BaseSkill[PythonRunInput, PythonRunOutput]):
    spec = SkillSpec(
        name="python.run",
        description="Execute Python code for calculations, data analysis, and visualization. 执行Python代码。",
        input_model=PythonRunInput,
        output_model=PythonRunOutput,
        side_effects={SideEffect.EXEC},
        risk_level=SkillRiskLevel.EXECUTE,
        aliases=["run_python", "execute_python", "python"],
    )

    async def run(self, ctx: SkillContext, params: PythonRunInput) -> PythonRunOutput:
        if ctx.dry_run:
            return PythonRunOutput(success=True, message="[dry_run] Would execute Python code", output="[Dry Run]", stdout="[Dry Run]")

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        img_buf = io.BytesIO()
        csv_buf = io.StringIO()

        try:
            import matplotlib
            matplotlib.use("Agg", force=True)
        except Exception:
            pass

        local_vars: Dict[str, Any] = {"base_path": str(ctx.base_path)}
        success = False
        error_msg = None
        base64_img = None
        dataframe_csv = None
        original_cwd = os.getcwd()

        try:
            if ctx.base_path:
                os.chdir(str(ctx.base_path))

            with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                exec(params.code, {"__builtins__": __builtins__}, local_vars)

                # Matplotlib hook
                if "matplotlib.pyplot" in sys.modules:
                    plt = sys.modules["matplotlib.pyplot"]
                    if plt.get_fignums():
                        try:
                            plt.savefig(img_buf, format="png", bbox_inches="tight")
                            plt.close("all")
                            img_buf.seek(0)
                            base64_img = base64.b64encode(img_buf.read()).decode("utf-8")
                        except Exception as e:
                            print(f"Error saving plot: {e}", file=stderr_buf)

                # Pandas DataFrame hook
                if "pandas" in sys.modules:
                    pd = sys.modules["pandas"]
                    target_df = local_vars.get("result")
                    if not isinstance(target_df, pd.DataFrame):
                        dfs = {k: v for k, v in local_vars.items() if isinstance(v, pd.DataFrame)}
                        target_df = dfs.get("df") or (list(dfs.values())[-1] if dfs else None)
                    if target_df is not None:
                        try:
                            target_df.iloc[:50, :20].to_csv(csv_buf, index=False)
                            dataframe_csv = csv_buf.getvalue()
                        except Exception as e:
                            print(f"Error saving dataframe: {e}", file=stderr_buf)

            success = True
        except Exception as e:
            traceback.print_exc(file=stderr_buf)
            error_msg = str(e)
        finally:
            os.chdir(original_cwd)

        output_stdout = stdout_buf.getvalue()
        output_stderr = stderr_buf.getvalue()

        safe_vars = {}
        for k, v in local_vars.items():
            if k.startswith("__") or k == "base_path":
                continue
            try:
                safe_vars[k] = v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else str(v)
            except Exception:
                safe_vars[k] = "<unserializable>"

        if success and ctx.execution_context:
            try:
                for var_name, var_value in safe_vars.items():
                    if not var_name.startswith("_"):
                        ctx.execution_context.variables.set(var_name, var_value)
            except Exception as e:
                logger.warning(f"[python.run] Failed to inject variables: {e}")

        result_val = local_vars.get("result")
        if result_val is None and success:
            user_vars = {k: v for k, v in safe_vars.items() if k != "result"}
            if len(user_vars) == 1:
                result_val = list(user_vars.values())[0]
            elif output_stdout.strip():
                result_val = output_stdout.strip()
            elif dataframe_csv:
                result_val = dataframe_csv
            elif base64_img:
                result_val = f"[Image: {len(base64_img)} bytes]"

        return PythonRunOutput(
            success=success,
            message="Execution completed" if success else f"Execution failed: {error_msg}",
            output=output_stdout,
            stdout=output_stdout,
            stderr=output_stderr,
            variables=safe_vars,
            result=result_val,
            base64_image=base64_img,
            dataframe_csv=dataframe_csv,
        )
