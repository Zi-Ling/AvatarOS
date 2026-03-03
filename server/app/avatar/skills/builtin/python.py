
import sys
import io
import traceback
import contextlib
import base64
import time
import logging
from typing import Any, Dict, Optional
from pydantic import Field

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)

class PythonRunInput(SkillInput):
    code: str = Field(..., description="The Python code to execute.")
    timeout: int = Field(30, description="Execution timeout in seconds (default 30s).")

class PythonRunOutput(SkillOutput):
    stdout: str = ""
    stderr: str = ""
    result: Optional[Any] = None
    variables: Dict[str, Any] = {}
    base64_image: Optional[str] = Field(None, description="Base64 encoded image if plot generated")
    dataframe_csv: Optional[str] = Field(None, description="CSV string if a pandas dataframe was detected")

@register_skill
class PythonRunSkill(BaseSkill[PythonRunInput, PythonRunOutput]):
    spec = SkillSpec(
        name="python.run",
        api_name="python.run",
        aliases=["run_python", "code.run", "execute_script", "plot", "draw", "visualize", "python.plot", "python.draw"],
        description="Execute Python code for mathematical calculations, data analysis, and visualization ONLY. Core capabilities: 1) Create plots and charts with matplotlib/seaborn (line plot, bar chart, scatter plot, heatmap, pie chart, function graphs). 2) Data analysis with pandas (DataFrames, CSV operations, statistics). 3) Complex mathematical calculations and algorithms. Automatically captures matplotlib plots as base64 images and pandas DataFrames as CSV. Common libraries: numpy, pandas, matplotlib, seaborn, scipy. 【专用于数学计算、数据分析和可视化】。核心能力：matplotlib/seaborn绘图（折线图、柱状图、散点图、热力图、饼图、函数图像）、pandas数据分析、复杂数学计算。自动捕获图表和数据框。",
        category=SkillCategory.SYSTEM,
        input_model=PythonRunInput,
        output_model=PythonRunOutput,
        
        # 参数别名映射（智能容错 - LLM 常见错误）
        param_aliases={
            "command": "code",      # LLM 有时会用 command 而不是 code
            "script": "code",       # 有些场景下可能叫 script
            "source": "code",       # 或者 source
            "python_code": "code",  # 或者更明确的 python_code
        },
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.COMPUTE,
            capabilities={SkillCapability.EXECUTE, SkillCapability.CREATE}, # Execution + Creation (plots, files)
            risk_level="critical",
            is_generic=False, # 标记为专用技能，用于绘图、数据分析等场景
            priority=30,  # 低优先级：有专用技能时优先使用专用技能
            min_match_score=0.50  # 高匹配阈值：只有明确需要计算/可视化时才出场
        ),
        
        synonyms=[
            # 核心定位：计算、数据分析、可视化
            "calculate",
            "compute",
            "process data",
            "data analysis",
            "data processing",
            "计算",
            "数据处理",
            "数据分析",
            # 图表类型（中文）
            "画图",
            "绘图",
            "可视化",
            "画图表",
            "画折线图",
            "画柱状图",
            "画散点图",
            "画饼图",
            "画热力图",
            "画直方图",
            "数据可视化",
            "统计图",
            "图表",
            "曲线",
            "函数图像",
            "函数图",
            # 三角函数和数学相关
            "正弦",
            "余弦",
            "正切",
            "函数",
            "数学",
            "数学计算",
            "方程",
            # 图表类型（英文）
            "plot",
            "chart",
            "graph",
            "visualize",
            "visualization",
            "sine",
            "cosine",
            "tangent",
            "line plot",
            "bar chart",
            "scatter plot",
            "pie chart",
            "heatmap",
            "histogram",
            "box plot",
            "violin plot",
            "contour plot",
            # 数据操作
            "dataframe",
            "pandas",
            "numpy",
            "statistics",
            "statistical analysis",
            "统计",
            "统计分析",
            # 注意：已移除以下通用词汇，避免过度出场
            # ❌ "write poem", "write article", "generate text", "create content"
            # ❌ "写诗", "写文章", "生成内容", "generate image", "draw"
        ],
        examples=[
            {
                "description": "Plot sine wave / 绘制正弦波",
                "params": {
                    "code": "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(0, 2*np.pi, 100)\ny = np.sin(x)\nplt.plot(x, y)\nplt.title('Sine Wave')\nplt.xlabel('x')\nplt.ylabel('sin(x)')\nplt.grid(True)"
                }
            },
            {
                "description": "Plot tangent function / 绘制正切函数",
                "params": {
                    "code": "import numpy as np\nimport matplotlib.pyplot as plt\nx = np.linspace(-np.pi, np.pi, 200)\ny = np.tan(x)\ny[np.abs(y) > 10] = np.nan\nplt.plot(x, y)\nplt.title('Tangent Function')\nplt.xlabel('x')\nplt.ylabel('tan(x)')\nplt.ylim(-10, 10)\nplt.grid(True)"
                }
            },
            {
                "description": "Draw bar chart / 绘制柱状图",
                "params": {
                    "code": "import matplotlib.pyplot as plt\ncategories = ['A', 'B', 'C', 'D']\nvalues = [23, 45, 56, 78]\nplt.bar(categories, values)\nplt.title('Sales Data')\nplt.xlabel('Category')\nplt.ylabel('Value')"
                }
            },
            {
                "description": "Data analysis with pandas / 数据分析",
                "params": {
                    "code": "import pandas as pd\ndf = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})\nprint(df.describe())\nresult = df"
                }
            },
            {
                "description": "Calculate sum of list / 计算列表和",
                "params": {
                    "code": "numbers = [1, 2, 3, 4, 5]\ntotal = sum(numbers)\nprint(f'Sum: {total}')\nresult = total"
                }
            },
            {
                "description": "Generate Excel file using pandas / 生成Excel文件",
                "params": {
                    "code": "import pandas as pd\ndf = pd.DataFrame({'Name': ['Alice', 'Bob'], 'Score': [95, 87]})\ndf.to_excel('test.xlsx', index=False)\nprint('Excel file created')"
                }
            }
        ],
        permissions=[
            SkillPermission(name="code_execution", description="Execute arbitrary Python code")
        ],
        tags=[
            # 核心技术栈
            "python", "code", "advanced",
            "matplotlib", "pandas", "numpy", "seaborn", "scipy",
            # 核心能力
            "calculation", "computation", "analysis", "visualization",
            "计算", "分析", "可视化", "绘图",
            "plot", "chart", "graph", "data",
            "math", "数学", "统计", "statistics",
            "画图", "图表", "数据", "函数",
            # 已移除：内容生成相关标签
            # ❌ "代码", "编程" (太通用)
        ]
    )

    async def run(self, ctx: SkillContext, params: PythonRunInput) -> PythonRunOutput:
        if ctx.dry_run:
            return PythonRunOutput(
                success=True, 
                message="[dry_run] Would execute Python code",
                stdout="[Dry Run Output]",
                result="[Dry Run Result]"
            )

        # Capture stdout/stderr
        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        
        # --- Matplotlib Hook Setup ---
        img_buffer = io.BytesIO()
        
        def save_plot_hook():
            # Check if matplotlib.pyplot was imported and has active figures
            # We check sys.modules because the user might import it inside the exec scope
            if 'matplotlib.pyplot' in sys.modules:
                plt = sys.modules['matplotlib.pyplot']
                # Only save if there are actually figures created
                if plt.get_fignums():
                    try:
                        plt.savefig(img_buffer, format='png', bbox_inches='tight')
                        plt.close('all')
                        return True
                    except Exception as e:
                        print(f"Error saving plot: {e}", file=stderr_buffer)
            return False

        # --- Pandas DataFrame Hook Setup ---
        csv_buffer = io.StringIO()
        
        def save_dataframe_hook(local_scope):
            # Heuristic: Look for 'df' or any variable that is a pandas DataFrame
            # and seems to be the intended output (e.g., 'result' or just left in scope)
            
            # Priority 1: Explicit 'result' variable that is a DataFrame
            target_df = local_scope.get('result')
            
            # Priority 2: Check if 'pandas' is imported and scan for DataFrames
            if 'pandas' in sys.modules:
                pd = sys.modules['pandas']
                
                if not isinstance(target_df, pd.DataFrame):
                    # Scan locals for any DataFrame, prefer 'df'
                    dfs = {k: v for k, v in local_scope.items() if isinstance(v, pd.DataFrame)}
                    if 'df' in dfs:
                        target_df = dfs['df']
                    elif dfs:
                        # If multiple, take the last defined one (roughly) or just the first found
                        # This is heuristic but often correct for simple scripts
                        target_df = list(dfs.values())[-1]
            
            if target_df is not None:
                # Check again if it's actually a DataFrame (in case Priority 1 matched but wasn't PD)
                # We need to be careful about type checking if PD wasn't imported globally? 
                # Actually, if we found it, it must be an instance of a class. 
                # We use duck typing or sys.modules to verify type to avoid import errors.
                type_name = type(target_df).__name__
                if type_name == 'DataFrame':
                    try:
                        # Safe Truncation
                        MAX_ROWS = 50
                        MAX_COLS = 20
                        
                        truncated = target_df.iloc[:MAX_ROWS, :MAX_COLS].copy()
                        
                        # Convert to CSV
                        truncated.to_csv(csv_buffer, index=False)
                        
                        # Add truncation notice if needed
                        if len(target_df) > MAX_ROWS or len(target_df.columns) > MAX_COLS:
                            # Append a special comment line or just let frontend handle "showing X of Y"
                            # For simplicity, we just return the truncated data.
                            pass
                            
                        return True
                    except Exception as e:
                        print(f"Error saving dataframe: {e}", file=stderr_buffer)
            
            return False

        # Helper to configure matplotlib backend (non-invasive)
        # 只配置必要的环境，不修改用户代码行为
        setup_code = """
import sys

# 1. Matplotlib Configuration (Agg backend only, no GUI)
try:
    import matplotlib
    matplotlib.use('Agg', force=True)
except Exception:
    pass
"""
        
        # Prepare execution environment
        # We inject some useful context like 'base_path' so scripts can use it
        local_vars = {
            "base_path": str(ctx.base_path),
            "print": lambda *args, **kwargs: print(*args, file=stdout_buffer, **kwargs)
        }
        
        # Safe(r) globals - allow standard imports but maybe restrict others if needed
        # For now, we allow standard python environment as requested for power-user mode
        global_vars = {
            "__builtins__": __builtins__,
        }

        success = False
        result_val = None
        error_msg = None
        base64_img = None
        dataframe_csv = None
        
        # 保存当前工作目录，执行后恢复
        import os
        import re
        original_cwd = os.getcwd()
        
        # ========== 鲁棒性增强：代码清洗与标准化 ==========
        # LLM 有时会在 JSON 中返回字面量的 \n (即 \\n)，导致 Python 解析错误
        # 我们需要将它们转换为真正的换行符，但要小心不要破坏字符串内部的结构
        
        def smart_cleanup_code(code: str) -> str:
            """
            智能清洗代码：
            1. 将结构性的字面量 \\n 转换为实际换行符
            2. 保持字符串内部的 \\n 原样（作为转义字符）
            """
            if not code: return code
            
            # 匹配 Python 字符串（包括三引号、单引号、双引号，以及前缀 f/r/u）
            # 优先匹配三引号（长字符串），然后是单行字符串
            string_pattern = r"""
                (?:f|r|u|fr|fu|rf|ur)?\"\"\"[\s\S]*?\"\"\"|  # 三双引号
                (?:f|r|u|fr|fu|rf|ur)?\'\'\'[\s\S]*?\'\'\'|  # 三单引号
                (?:f|r|u|fr|fu|rf|ur)?\"(?:[^"\\\n]|\\.)*\"| # 双引号
                (?:f|r|u|fr|fu|rf|ur)?\'(?:[^'\\\n]|\\.)*\'  # 单引号
            """
            
            # 匹配我们要处理的目标：字面量的 \n (即使前面有空格)
            target_pattern = r"\\n"
            
            # 组合正则
            pattern = re.compile(f"({string_pattern})|({target_pattern})", re.VERBOSE | re.MULTILINE)
            
            def replace_func(match):
                if match.group(1):
                    # 如果匹配到字符串，原样返回（保护字符串内部的 \n）
                    return match.group(1)
                else:
                    # 如果匹配到结构性的 \n，替换为真正的换行
                    return "\n"
                    
            cleaned = pattern.sub(replace_func, code)
            
            # 去除可能残留的 markdown 标记
            cleaned = cleaned.strip()
            if cleaned.startswith("```python"):
                cleaned = cleaned[9:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
                
            return cleaned

        raw_code = params.code
        if raw_code:
            try:
                params.code = smart_cleanup_code(raw_code)
            except Exception as e:
                # 如果正则处理失败（极其罕见），回退到简单替换，虽然有风险但比崩了强
                logger.debug(f"[python.run] Smart cleanup failed: {e}, falling back to simple replace")
                params.code = raw_code.replace('\\n', '\n')
            
        logger.debug(f"[python.run] Executing code (cleaned):\n{params.code}")

        # ========== 鲁棒性增强：执行前语法验证 ==========
        try:
            compile(params.code, '<user_code>', 'exec')
            logger.debug("[python.run] Syntax validation passed")
        except SyntaxError as e:
            error_msg = f"Syntax error at line {e.lineno}: {e.msg}"
            logger.debug(f"[python.run] Syntax validation failed: {error_msg}")
            # 直接返回失败，不执行
            return PythonRunOutput(
                success=False,
                message=f"Code validation failed: {error_msg}",
                stdout="",
                stderr=f"SyntaxError: {error_msg}\n{e.text or ''}",
                variables={},
                result=None,
                base64_image=None,
                dataframe_csv=None,
                fs_operation=None,
                fs_path=None,
                fs_type=None
            )
        
        try:
            # ========== Phase 3.2: 执行前环境检查 ==========
            logger.debug(
                f"[python.run] Environment: exe={sys.executable}, "
                f"ver={sys.version.split()[0]}, cwd={os.getcwd()}"
            )
            # ===============================================
            
            # 切换到工作目录，确保相对路径文件操作在正确的目录下
            if ctx.base_path:
                os.chdir(str(ctx.base_path))
                logger.debug(f"[python.run] Working directory changed to: {ctx.base_path}")
            
            # Execute setup code first (for matplotlib backend)
            # Note: We must execute setup in the same scope as user code if we want imports to persist
            # But here we just want to set the backend globally for the process/module
            exec(setup_code, global_vars, local_vars)

            # Execute the code
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                # 1. Execute the code block
                exec(params.code, global_vars, local_vars)
                
                # 2. Check for plots
                if save_plot_hook():
                     img_buffer.seek(0)
                     base64_img = base64.b64encode(img_buffer.read()).decode('utf-8')
                
                # 3. Check for DataFrames
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
            # 恢复原始工作目录
            os.chdir(original_cwd)

        output_stdout = stdout_buffer.getvalue()
        output_stderr = stderr_buffer.getvalue()
        
        # Filter out unserializable variables from local_vars to return
        safe_vars = {}
        for k, v in local_vars.items():
            if k.startswith("__") or k in ["base_path", "print", "matplotlib", "plt"]:
                continue
            try:
                # Basic check if json serializable (primitive types)
                # or simple string representation
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    safe_vars[k] = v
                else:
                    safe_vars[k] = str(v)
            except:
                safe_vars[k] = "<unserializable>"
        
        # 🎯 [方案1-步骤1: 变量自动捕获与注入] - 黑板模式核心
        # 把所有局部变量自动注入到 TaskContext，供下游步骤使用
        if success and ctx.execution_context:
            try:
                import datetime
                # 只注入有意义的变量（非私有、非内置）
                for var_name, var_value in safe_vars.items():
                    if not var_name.startswith("_"):
                        # 注入到 TaskContext.variables（黑板）
                        ctx.execution_context.variables.set(var_name, var_value)
                        
                        # 如果是重要数据类型，同时注册为 Artifact（支持语义查找）
                        if isinstance(var_value, (str, int, float, datetime.datetime)):
                            artifact_type = "variable"
                            if isinstance(var_value, datetime.datetime):
                                artifact_type = "variable:datetime"
                            elif isinstance(var_value, str) and len(var_value) > 100:
                                artifact_type = "variable:text"
                            
                            ctx.execution_context.artifacts.add(
                                type=artifact_type,
                                uri=f"var://{var_name}",
                                meta={
                                    "name": var_name,
                                    "value": var_value,
                                    "value_type": type(var_value).__name__,
                                    "created_at": time.time(),
                                    "skill": "python.run"
                                }
                            )
                
                logger.debug(
                    f"[python.run] ✅ Captured {len(safe_vars)} variables to TaskContext "
                    f"(blackboard mode)"
                )
            except Exception as e:
                logger.warning(f"[python.run] Failed to inject variables to context: {e}")
        
        # 🎯 [防止 python.run 乱入] 步骤3：智能隐式返回
        # 当 result 为 None 时，从以下来源提取有意义的值：
        # 1. 用户定义的变量（过滤掉内置和私有）
        # 2. stdout（print 输出）
        # 3. dataframe_csv（pandas 结果）
        # 4. base64_img（图表）
        result_val = local_vars.get("result")
        
        if result_val is None and success:
            fallback_source = None
            
            # 优先级0: 用户定义的变量（最智能的兜底）
            # 如果只有一个用户变量，很可能就是想要的结果
            user_vars = {
                k: v for k, v in safe_vars.items()
                if not k.startswith("_") and k not in ["result"]
            }
            
            if len(user_vars) == 1:
                # 只有一个用户变量，很可能就是结果
                var_name, var_value = list(user_vars.items())[0]
                result_val = var_value
                fallback_source = f"variable:{var_name}"
                logger.warning(
                    f"[python.run] 🎯 Implicit return: extracted single user variable '{var_name}' "
                    f"as result (type: {type(var_value).__name__})"
                )
            
            # 优先级1: stdout
            elif isinstance(output_stdout, str) and output_stdout.strip():
                result_val = output_stdout.strip()
                fallback_source = "stdout"
            
            # 优先级2: dataframe_csv
            elif dataframe_csv and isinstance(dataframe_csv, str) and dataframe_csv.strip():
                result_val = dataframe_csv
                fallback_source = "dataframe_csv"
            
            # 优先级3: base64_img
            elif base64_img:
                result_val = f"[Image Generated: {len(base64_img)} bytes]"
                fallback_source = "base64_image"
            
            if fallback_source and fallback_source != f"variable:{list(user_vars.keys())[0]}" if user_vars else None:
                logger.warning(
                    f"[python.run] 'result' is None, falling back to '{fallback_source}' "
                    f"(length: {len(str(result_val))})"
                )
        else:
            result_val = local_vars.get("result")

        # 检测是否生成了新文件（用于触发文件刷新）
        # fs_operation = None
        # fs_path = None
        # fs_type = None
        # 
        # if success and ctx.base_path:
        #     # 检查输出中是否包含文件保存的关键词
        #     output_text = output_stdout.lower()
        #     if any(keyword in output_text for keyword in ['saved', '保存', 'created', '创建', '.csv', '.xlsx', '.png', '.jpg']):
        #         # 简单标记：有文件操作发生
        #         fs_operation = 'created'
        #         fs_type = 'file'
        #         # TODO: 更精确的文件路径提取可以后续优化

        result_output = PythonRunOutput(
            success=success,
            message="Execution completed" if success else f"Execution failed: {error_msg}",
            stdout=output_stdout,
            stderr=output_stderr,
            variables=safe_vars,
            # 使用修正后的 result_val（带兜底逻辑）
            result=result_val,
            base64_image=base64_img,
            dataframe_csv=dataframe_csv,
            # 文件系统操作元数据
            fs_operation=None, # 让 Watcher 处理
            fs_path=None,
            fs_type=None
        )
        
        logger.debug(f"[python.run] Final result: success={success}, stderr_length={len(output_stderr)}")
        if output_stderr:
            logger.debug(f"[python.run] Stderr content:\n{output_stderr}")
        
        return result_output
