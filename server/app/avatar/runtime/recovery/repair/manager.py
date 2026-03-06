# app/avatar/runtime/recovery/repair/manager.py
"""
代码自动修复管理器
"""
from __future__ import annotations

import logging
import json
import re
import time
from typing import Optional, Any, Dict
from dataclasses import dataclass
from datetime import datetime

from .validator import RepairValidator
from .patch import PatchApplier

logger = logging.getLogger(__name__)


# ==================== 数据模型 ====================
# RepairSnapshot 已废弃，改用 TaskContext.status.repair_state

@dataclass
class RepairResult:
    """修复结果"""
    success: bool
    fixed_code: Optional[str] = None
    patch: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempt_number: int = 0  # 新增：尝试次数


# ==================== Prompt 模板 ====================

REPAIR_PROMPT_TEMPLATE = """You are a code repair assistant. Your task is to fix a Python execution error with MINIMAL changes.

⚠️ CRITICAL RULES (MUST FOLLOW):
1. Make MINIMAL changes - ONLY fix the specific error
2. Do NOT rewrite, refactor, or optimize unrelated code
3. Do NOT change the overall logic or structure
4. Keep ALL existing functionality intact
5. This is repair attempt #{repair_count}/2 - be extra careful!

📋 TASK CONTEXT:
The user's goal: {task_goal}

📝 ORIGINAL CODE (with line numbers):
{code_with_lines}

❌ ERROR MESSAGE:
{error_msg}

{error_hint}

💡 COMMON FIXES:
- Missing import? → Add ONE import line at the top
- Variable undefined? → Check for typos in variable names
- Syntax error? → Fix ONLY that specific line
- Module not found? → Add the correct import statement

📦 OUTPUT FORMAT (JSON):
You MUST output a JSON object with ONE of these formats:

Option 1 - Insert lines (for adding imports, etc.):
{{
  "patch_type": "insert",
  "edits": [
    {{
      "line": 1,
      "content": "import random  # FIX: missing import"
    }}
  ],
  "reasoning": "Added missing import for random module"
}}

Option 2 - Replace block (for fixing specific lines):
{{
  "patch_type": "replace",
  "start_line": 12,
  "end_line": 15,
  "new_code": "fixed code here\\ncan be multiple lines",
  "reasoning": "Fixed syntax error in the calculation"
}}

⚠️ IMPORTANT:
- Line numbers start from 1
- Only modify lines related to the error
- Do NOT return the full code, ONLY the patch
- Explain your reasoning briefly

Generate the repair patch (JSON only):
"""


# ==================== 核心管理器 ====================

class CodeRepairManager:
    """
    代码自动修复管理器
    
    基于 JSON Patch 的 Minimal 修复策略
    """
    
    def __init__(self, llm_client, max_attempts: int = 2):
        """
        Args:
            llm_client: LLM 客户端
            max_attempts: 最大修复尝试次数（默认 2）
        """
        self.llm = llm_client
        self.max_attempts = max_attempts
    
    async def attempt_repair(
        self, 
        step: Any,  # Step object
        error_msg: str,
        task_goal: str,
        task_context: Any = None  # TaskContext（新架构：必需）
    ) -> RepairResult:
        """
        尝试修复失败的代码（新架构：使用 TaskContext 结构化状态）
        
        Args:
            step: 失败的步骤对象
            error_msg: 错误消息
            task_goal: 任务目标（用于上下文）
            task_context: TaskContext（存储 repair 状态）
            
        Returns:
            RepairResult: 修复结果
        """
        if not task_context:
            logger.error("[Repair] TaskContext is required for repair (new architecture)")
            return RepairResult(success=False, error="TaskContext missing")
        
        original_code = step.params.get("code", "")
        if not original_code:
            return RepairResult(success=False, error="No code to repair")
        
        # Phase 1: 初始化或获取 repair 状态（从结构化存储）
        repair_state = task_context.status.repair_state
        
        if not repair_state.is_repairing:
            # 第一次修复：初始化状态
            repair_state.is_repairing = True
            repair_state.failed_step_id = step.id
            repair_state.original_code = original_code
            repair_state.original_error = error_msg
            repair_state.current_attempt = 0
            task_context.save_snapshot()  # 持久化到 MemoryManager
            logger.info(f"[Repair] Initialized repair state for step {step.id}")
        
        repair_count = repair_state.current_attempt
        logger.info(f"[Repair] Attempting repair #{repair_count + 1}/{repair_state.max_attempts} for step {step.id}")
        
        try:
            # Phase 2: 生成 JSON Patch
            patch = await self._generate_json_patch(
                original_code, 
                error_msg, 
                task_goal,
                repair_count
            )
            
            if not patch:
                # 记录失败的尝试
                self._record_attempt(task_context, repair_count + 1, "generate", patch, "failed", "Failed to generate patch")
                return RepairResult(
                    success=False, 
                    error="Failed to generate patch",
                    attempt_number=repair_count + 1
                )
            
            # Phase 3: 在临时副本上应用 Patch
            temp_code = PatchApplier.apply_patch(original_code, patch)
            
            if not temp_code:
                # 记录失败的尝试
                self._record_attempt(task_context, repair_count + 1, patch.get("patch_type", "unknown"), patch, "failed", "Failed to apply patch")
                return RepairResult(
                    success=False,
                    error="Failed to apply patch",
                    attempt_number=repair_count + 1
                )
            
            # Phase 4: 验证修复
            validation_result = RepairValidator.validate(temp_code, error_msg)
            
            if validation_result.success:
                logger.info(f"[Repair] ✅ Repair successful for step {step.id}")
                # 记录成功的尝试
                self._record_attempt(task_context, repair_count + 1, patch.get("patch_type", "unknown"), patch, "success", None)
                # 清理 repair 状态
                repair_state.is_repairing = False
                task_context.save_snapshot()
                
                return RepairResult(
                    success=True,
                    fixed_code=temp_code,
                    patch=patch,
                    attempt_number=repair_count + 1
                )
            else:
                logger.warning(f"[Repair] ❌ Validation failed at {validation_result.level}: {validation_result.error}")
                # 记录验证失败的尝试
                self._record_attempt(task_context, repair_count + 1, patch.get("patch_type", "unknown"), patch, "validation_failed", validation_result.error)
                return RepairResult(
                    success=False,
                    error=f"Validation failed: {validation_result.error}",
                    attempt_number=repair_count + 1
                )
                
        except Exception as e:
            logger.error(f"[Repair] Exception during repair: {e}")
            # 记录异常
            self._record_attempt(task_context, repair_count + 1, "unknown", {}, "failed", str(e))
            return RepairResult(
                success=False,
                error=f"Repair exception: {e}",
                attempt_number=repair_count + 1
            )
    
    def _record_attempt(
        self,
        task_context: Any,
        attempt_number: int,
        patch_type: str,
        patch_data: Dict[str, Any],
        result: str,
        error: Optional[str] = None
    ) -> None:
        """
        记录一次修复尝试到结构化存储
        
        Args:
            task_context: TaskContext
            attempt_number: 尝试次数
            patch_type: Patch 类型
            patch_data: Patch 数据
            result: 结果状态
            error: 错误信息（如果失败）
        """
        from app.avatar.runtime.core.context import RepairAttempt
        
        repair_state = task_context.status.repair_state
        attempt = RepairAttempt(
            attempt_number=attempt_number,
            timestamp=time.time(),
            patch_type=patch_type,
            patch_data=patch_data,
            result=result,
            error_after_repair=error
        )
        
        repair_state.add_attempt(attempt)
        task_context.save_snapshot()  # 持久化到 MemoryManager
        
        logger.info(f"[Repair] Recorded attempt #{attempt_number}: {result}")
    
    async def _generate_json_patch(
        self,
        original_code: str,
        error_msg: str,
        task_goal: str,
        repair_count: int
    ) -> Optional[Dict[str, Any]]:
        """
        让 LLM 生成 JSON Patch（结构化的 edits）
        
        Returns:
            JSON patch 对象，或 None 如果失败
        """
        # 添加行号
        code_with_lines = self._add_line_numbers(original_code)
        
        # 分析错误位置
        error_hint = self._generate_error_hint(error_msg)
        
        # 构建 prompt
        prompt = REPAIR_PROMPT_TEMPLATE.format(
            repair_count=repair_count + 1,
            task_goal=task_goal,
            code_with_lines=code_with_lines,
            error_msg=error_msg,
            error_hint=error_hint
        )
        
        try:
            # 调用 LLM
            response = await self._call_llm(prompt)
            
            # 解析 JSON
            patch = self._extract_json_patch(response)
            
            if patch:
                logger.info(f"[Repair] Generated patch: {patch.get('patch_type', 'unknown')}")
                return patch
            else:
                logger.warning("[Repair] Failed to extract valid JSON patch from LLM response")
                return None
                
        except Exception as e:
            logger.error(f"[Repair] Failed to generate patch: {e}")
            return None
    
    def rollback(self, step: Any, task_context: Any):
        """
        回滚到原始代码（新架构：从 TaskContext.status.repair_state 获取）
        
        Args:
            step: 步骤对象
            task_context: TaskContext（包含 repair_state）
        """
        if not task_context:
            logger.warning("[Repair] No task_context provided for rollback")
            return
        
        repair_state = task_context.status.repair_state
        
        if not repair_state.original_code:
            logger.warning("[Repair] No original code to rollback to")
            return
        
        step.params["code"] = repair_state.original_code
        logger.info(f"[Repair] ⏮️  Rolled back step {step.id} to original code")
        
        # 清理 repair 状态
        repair_state.is_repairing = False
        task_context.save_snapshot()
    
    # ==================== 辅助方法 ====================
    
    def _add_line_numbers(self, code: str) -> str:
        """为代码添加行号"""
        lines = code.split('\n')
        numbered = []
        for i, line in enumerate(lines, 1):
            numbered.append(f"{i:3d} | {line}")
        return '\n'.join(numbered)
    
    def _generate_error_hint(self, error_msg: str) -> str:
        """根据错误类型生成提示"""
        if "ModuleNotFoundError" in error_msg or "ImportError" in error_msg:
            module = RepairValidator._extract_missing_module(error_msg)
            if module:
                return f"💡 HINT: Missing import for module '{module}'. Add import at the top of the file."
        
        elif "NameError" in error_msg:
            return "💡 HINT: Variable or function not defined. Check for typos or missing initialization."
        
        elif "SyntaxError" in error_msg:
            return "💡 HINT: Syntax error. Check for missing colons, parentheses, or indentation issues."
        
        elif "IndentationError" in error_msg:
            return "💡 HINT: Indentation error. Ensure consistent use of spaces or tabs."
        
        return ""
    
    def _extract_json_patch(self, response: str) -> Optional[Dict[str, Any]]:
        """从 LLM 响应中提取 JSON patch"""
        try:
            response_clean = response.strip()
            
            # 移除 markdown 代码块
            if "```json" in response_clean:
                match = re.search(r"```json\s*(.*?)\s*```", response_clean, re.DOTALL)
                if match:
                    response_clean = match.group(1)
            elif "```" in response_clean:
                match = re.search(r"```\s*(.*?)\s*```", response_clean, re.DOTALL)
                if match:
                    response_clean = match.group(1)
            
            # 提取 JSON 对象
            start = response_clean.find('{')
            end = response_clean.rfind('}')
            
            if start != -1 and end != -1 and start < end:
                json_str = response_clean[start:end+1]
                patch = json.loads(json_str)
                
                # 验证 patch 结构
                if PatchApplier.validate_patch_structure(patch):
                    return patch
                else:
                    logger.warning("[Repair] Invalid patch structure")
                    return None
            else:
                logger.warning("[Repair] Could not find JSON object in response")
                return None
                
        except json.JSONDecodeError as e:
            logger.error(f"[Repair] Failed to parse JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"[Repair] Failed to extract JSON patch: {e}")
            return None
    
    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        try:
            if hasattr(self.llm, "call"):
                import asyncio
                if asyncio.iscoroutinefunction(self.llm.call):
                    response = await self.llm.call(prompt)
                else:
                    # 同步方法在 executor 中运行
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, self.llm.call, prompt)
            elif hasattr(self.llm, "generate"):
                response = await self.llm.generate(prompt)
            elif callable(self.llm):
                response = await self.llm(prompt)
            else:
                raise TypeError("LLM client is not callable")
            
            return response
            
        except Exception as e:
            logger.error(f"[Repair] LLM call failed: {e}")
            raise

