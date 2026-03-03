# app/avatar/runtime/recovery/repair/patch.py
"""
JSON Patch 应用逻辑
"""
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class PatchApplier:
    """JSON Patch 应用器"""
    
    @staticmethod
    def apply_insert(lines: List[str], edits: List[Dict]) -> List[str]:
        """
        插入行（通常用于添加 import）
        
        Args:
            lines: 代码行列表
            edits: 编辑列表，每个包含 line 和 content
        
        Returns:
            修改后的代码行列表
        """
        # 按行号倒序排序，避免插入后行号偏移
        edits_sorted = sorted(edits, key=lambda x: x.get('line', 0), reverse=True)
        
        for edit in edits_sorted:
            line_no = edit.get('line', 1)
            content = edit.get('content', '')
            
            # 行号从 1 开始，转换为索引（从 0 开始）
            insert_index = line_no - 1
            
            # 边界检查
            if insert_index < 0:
                insert_index = 0
            elif insert_index > len(lines):
                insert_index = len(lines)
            
            lines.insert(insert_index, content)
            logger.info(f"[Patch] Inserted line at {line_no}: {content[:50]}...")
        
        return lines
    
    @staticmethod
    def apply_replace(lines: List[str], start_line: int, end_line: int, new_code: str) -> List[str]:
        """
        替换代码块
        
        Args:
            lines: 代码行列表
            start_line: 起始行号（从 1 开始）
            end_line: 结束行号（从 1 开始，包含）
            new_code: 新代码（可能包含多行）
        
        Returns:
            修改后的代码行列表
        """
        # 转换为索引
        start_idx = start_line - 1
        end_idx = end_line  # end_line 本身也要被替换，所以不用 -1
        
        # 边界检查
        if start_idx < 0:
            start_idx = 0
        if end_idx > len(lines):
            end_idx = len(lines)
        
        # 替换
        new_lines = new_code.split('\n') if new_code else []
        lines[start_idx:end_idx] = new_lines
        
        logger.info(f"[Patch] Replaced lines {start_line}-{end_line} with {len(new_lines)} new lines")
        
        return lines
    
    @staticmethod
    def apply_patch(original_code: str, patch: Dict[str, Any]) -> Optional[str]:
        """
        应用 JSON Patch 到代码
        
        支持两种类型：
        1. insert: 插入行
        2. replace: 替换代码块
        
        Args:
            original_code: 原始代码
            patch: JSON patch 对象
        
        Returns:
            修复后的代码，或 None 如果失败
        """
        try:
            lines = original_code.split('\n')
            patch_type = patch.get('patch_type')
            
            if patch_type == 'insert':
                # 插入行
                edits = patch.get('edits', [])
                lines = PatchApplier.apply_insert(lines, edits)
            
            elif patch_type == 'replace':
                # 替换代码块
                start_line = patch.get('start_line', 1)
                end_line = patch.get('end_line', 1)
                new_code = patch.get('new_code', '')
                lines = PatchApplier.apply_replace(lines, start_line, end_line, new_code)
            
            else:
                logger.error(f"[Patch] Unknown patch type: {patch_type}")
                return None
            
            return '\n'.join(lines)
            
        except Exception as e:
            logger.error(f"[Patch] Failed to apply patch: {e}")
            return None
    
    @staticmethod
    def validate_patch_structure(patch: Dict[str, Any]) -> bool:
        """验证 patch 结构是否正确"""
        patch_type = patch.get('patch_type')
        
        if patch_type == 'insert':
            # 必须有 edits 数组
            edits = patch.get('edits', [])
            if not isinstance(edits, list) or len(edits) == 0:
                return False
            
            # 每个 edit 必须有 line 和 content
            for edit in edits:
                if not isinstance(edit, dict):
                    return False
                if 'line' not in edit or 'content' not in edit:
                    return False
            
            return True
        
        elif patch_type == 'replace':
            # 必须有 start_line, end_line, new_code
            required = ['start_line', 'end_line', 'new_code']
            return all(key in patch for key in required)
        
        return False

