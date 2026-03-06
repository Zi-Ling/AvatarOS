# server/app/avatar/skills/core/python_skill.py

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

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability, SkillRiskLevel, ExecutionClass
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


# ============================================================================
# python.run - 简化版本（移除 RestrictedPython）
# ============================================================================

class PythonRunInput(SkillInput):
    code: str = Field(..., description="Python code to execute")
    timeout: int = Field(30, description="Execution timeout in seconds (default 30s)")

class PythonRunOutput(SkillOutput):
    output: str = Field("", description="Primary output: stdout content")  # ← 新增标准字段
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
        api_name="python.run",
        aliases=["run_python", "execute_python", "python"],
        description="Execute Python code for calculations, data analysis, and visualization. Supports: numpy, pandas, matplotlib, seaborn, scipy. 执行Python代码，用于计算、数据分析和可视化。",
        category=SkillCategory.SYSTEM,
        input_model=PythonRunInput,
        output_model=PythonRunOutput,
        
        meta=SkillMetadata(
            domain=SkillDomain.COMPUTE,
            capabilities={SkillCapability.EXECUTE},
            risk_level=SkillRiskLevel.EXECUTE,
            exec_class=ExecutionClass.SANDBOX,  # 动态代码强制 SANDBOX
            is_generic=False,
            priority=10,
        ),
        
        synonyms=[
            "calculate", "compute", "process data", "data analysis",
            "plot", "chart", "visualize", "visualization",
            "计算", "数据处理", "数据分析", "画图", "绘图", "可视化",
        ],
        
        examples=[
            {
                "description": "Calculate sum",
                "params": {"code": "result = sum([1, 2, 3, 4, 5])"}
            },
            {
                "description": "Plot sine wave",
                "params": {"code": "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(0, 2*np.pi, 100)\ny = np.sin(x)\nplt.plot(x, y)\nplt.title('Sine Wave')"}
            },
        ],
        
        permissions=[
            SkillPermission(name="code_execution", description="Execute Python code")
        ],
        
        tags=["python", "code", "calculation", "visualization", "计算", "可视化"]
    )

    async def run(self, ctx: SkillContext, params: PythonRunInput) -> PythonRunOutput:
        if ctx.dry_run:
            return PythonRunOutput(
                success=True,
                message="[dry_run] Would execute Python code",
                output="[Dry Run Output]",  # ← 新增
                stdout="[Dry Run Output]"
            )

        # Capture stdout/stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        # Matplotlib hook
        img_buffer = io.BytesIO()
        
        def save_plot_hook():
            if 'matplotlib.pyplot' in sys.modules:
                plt = sys.modules['matplotlib.pyplot']
                if plt.get_fignums():
                    try:
                        plt.savefig(img_buffer, format='png', bbox_inches='tight')
                        plt.close('all')
                        return True
                    except Exception as e:
                        print(f"Error saving plot: {e}", file=stderr_buffer)
            return False

        # Pandas DataFrame hook
        csv_buffer = io.StringIO()
        
        def save_dataframe_hook(local_scope):
            target_df = local_scope.get('result')
            
            if 'pandas' in sys.modules:
                pd = sys.modules['pandas']
                
                if not isinstance(target_df, pd.DataFrame):
                    dfs = {k: v for k, v in local_scope.items() if isinstance(v, pd.DataFrame)}
                    if 'df' in dfs:
                        target_df = dfs['df']
                    elif dfs:
                        target_df = list(dfs.values())[-1]
            
            if target_df is not None and type(target_df).__name__ == 'DataFrame':
                try:
                    MAX_ROWS = 50
                    MAX_COLS = 20
                    truncated = target_df.iloc[:MAX_ROWS, :MAX_COLS].copy()
                    truncated.to_csv(csv_buffer, index=False)
                    return True
                except Exception as e:
                    print(f"Error saving dataframe: {e}", file=stderr_buffer)
            
            return False

        # Matplotlib backend setup
        try:
            import matplotlib
            matplotlib.use('Agg', force=True)
        except Exception:
            pass
        
        # Prepare execution environment
        local_vars = {
            "base_path": str(ctx.base_path),
        }

        success = False
        result_val = None
        error_msg = None
        base64_img = None
        dataframe_csv = None
        
        original_cwd = os.getcwd()
        
        try:
            # 切换到工作目录
            if ctx.base_path:
                os.chdir(str(ctx.base_path))
                logger.debug(f"[python.run] Working directory: {ctx.base_path}")
            
            # Execute user code
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(params.code, {"__builtins__": __builtins__}, local_vars)
                
                # Check for plots
                if save_plot_hook():
                    img_buffer.seek(0)
                    base64_img = base64.b64encode(img_buffer.read()).decode('utf-8')
                
                # Check for DataFrames
                if save_dataframe_hook(local_vars):
                    dataframe_csv = csv_buffer.getvalue()

            success = True
            logger.debug("[python.run] Execution completed successfully")
            
        except Exception as e:
            traceback.print_exc(file=stderr_buffer)
            error_msg = str(e)
            success = False
            logger.debug(f"[python.run] Execution failed: {error_msg}")
        finally:
            os.chdir(original_cwd)

        output_stdout = stdout_buffer.getvalue()
        output_stderr = stderr_buffer.getvalue()
        
        # Filter safe variables
        safe_vars = {}
        for k, v in local_vars.items():
            if k.startswith("__") or k in ["base_path"]:
                continue
            try:
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    safe_vars[k] = v
                else:
                    safe_vars[k] = str(v)
            except:
                safe_vars[k] = "<unserializable>"
        
        # Inject variables to TaskContext (blackboard mode)
        if success and ctx.execution_context:
            try:
                for var_name, var_value in safe_vars.items():
                    if not var_name.startswith("_"):
                        ctx.execution_context.variables.set(var_name, var_value)
                
                logger.debug(f"[python.run] Captured {len(safe_vars)} variables to TaskContext")
            except Exception as e:
                logger.warning(f"[python.run] Failed to inject variables: {e}")
        
        # Smart implicit return
        result_val = local_vars.get("result")
        
        if result_val is None and success:
            user_vars = {
                k: v for k, v in safe_vars.items()
                if not k.startswith("_") and k not in ["result"]
            }
            
            if len(user_vars) == 1:
                var_name, var_value = list(user_vars.items())[0]
                result_val = var_value
                logger.debug(f"[python.run] Implicit return from variable: {var_name}")
            elif output_stdout.strip():
                result_val = output_stdout.strip()
            elif dataframe_csv:
                result_val = dataframe_csv
            elif base64_img:
                result_val = f"[Image Generated: {len(base64_img)} bytes]"

        return PythonRunOutput(
            success=success,
            message="Execution completed" if success else f"Execution failed: {error_msg}",
            output=output_stdout,  # ← 新增：主输出指向 stdout
            stdout=output_stdout,
            stderr=output_stderr,
            variables=safe_vars,
            result=result_val,
            base64_image=base64_img,
            dataframe_csv=dataframe_csv
        )
