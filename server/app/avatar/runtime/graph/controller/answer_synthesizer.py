"""
AnswerSynthesizer — Rule-based final answer generation.

Traverses completed graph nodes and produces a human-readable summary
grouped by task type (data analysis, file generation, chart, etc.).
No LLM calls; pure deterministic extraction.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.avatar.runtime.graph.models.execution_graph import ExecutionGraph

logger = logging.getLogger(__name__)

# Extension → human-friendly category
_EXT_CATEGORY = {
    ".png": "图表", ".jpg": "图片", ".jpeg": "图片", ".svg": "矢量图",
    ".gif": "图片", ".csv": "数据表格", ".xlsx": "电子表格",
    ".xls": "电子表格", ".json": "JSON 数据", ".md": "Markdown 文档",
    ".txt": "文本文件", ".html": "HTML 文档", ".pdf": "PDF 文档",
}


class AnswerSynthesizer:
    """Synthesize a human-readable summary from graph execution results."""

    @staticmethod
    def synthesize(graph: 'ExecutionGraph', intent: str) -> Optional[str]:
        """Return a concise summary string, or *None* if nothing useful."""
        try:
            return AnswerSynthesizer._do_synthesize(graph, intent)
        except Exception as exc:
            logger.debug(f"[AnswerSynthesizer] Failed: {exc}")
            return None

    @staticmethod
    def _do_synthesize(graph: 'ExecutionGraph', intent: str) -> Optional[str]:
        from app.avatar.runtime.graph.models.step_node import NodeStatus

        success_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SUCCESS
        ]
        if not success_nodes:
            return None

        artifacts: List[Dict[str, str]] = []   # {"path", "category", "desc"}
        numeric_results: List[str] = []
        text_snippets: List[str] = []

        for node in success_nodes:
            meta = node.metadata or {}
            outputs = node.outputs or {}

            # ── Collect artifact semantic info ──────────────────────
            for art in meta.get("artifact_semantic", []):
                ext = Path(art["path"]).suffix.lower()
                cat = _EXT_CATEGORY.get(ext, "文件")
                artifacts.append({
                    "path": art["path"],
                    "category": cat,
                    "desc": art.get("source_description", ""),
                })

            # ── Extract numeric highlights from stdout / output ────
            raw = outputs.get("stdout") or outputs.get("output") or outputs.get("result")
            if isinstance(raw, dict):
                # Look for common summary keys
                for key in ("overall_total", "total", "sum", "average",
                            "overall_average", "count", "mean"):
                    if key in raw:
                        numeric_results.append(f"{key}: {raw[key]}")
            elif isinstance(raw, str) and len(raw) < 2000:
                # Grab lines that look like key-value results
                for line in raw.splitlines():
                    line = line.strip()
                    if re.match(r'^[\w\s\u4e00-\u9fff]+[:：]\s*[\d,.]+', line):
                        numeric_results.append(line)

            # ── Collect short text outputs (e.g. text-answer skills) ──
            _is_answer = False
            try:
                from app.avatar.skills.registry import skill_registry as _sr
                _is_answer = _sr.is_answer_skill(node.capability_name)
            except Exception:
                pass
            if _is_answer:
                answer = (
                    outputs.get("result")
                    or outputs.get("response_zh")
                    or outputs.get("content")
                    or outputs.get("text")
                    or ""
                )
                if isinstance(answer, str) and 10 < len(answer) < 1500:
                    text_snippets.append(answer.strip())

        # ── Assemble summary ────────────────────────────────────────
        parts: List[str] = []

        if numeric_results:
            parts.append("📊 计算结果：")
            for nr in numeric_results[:10]:
                parts.append(f"  • {nr}")

        if artifacts:
            parts.append("📁 生成的文件：")
            for art in artifacts:
                label = f"{art['category']}: {art['path']}"
                if art["desc"]:
                    label += f" ({art['desc'][:60]})"
                parts.append(f"  • {label}")

        if text_snippets:
            # Use the last (most complete) text snippet
            parts.append("💬 分析结论：")
            parts.append(text_snippets[-1][:800])

        # ── Warnings for failed/skipped nodes ──────────────────────
        failed_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.FAILED
        ]
        skipped_nodes = [
            n for n in graph.nodes.values() if n.status == NodeStatus.SKIPPED
        ]
        if failed_nodes:
            parts.append(f"⚠️ {len(failed_nodes)} 个步骤执行失败（已通过重试恢复）")
        if skipped_nodes:
            parts.append(f"⏭️ {len(skipped_nodes)} 个步骤被跳过")

        if not parts:
            # Fallback: just list what skills ran successfully
            skill_names = [n.capability_name for n in success_nodes]
            parts.append(f"已完成 {len(success_nodes)} 个步骤 ({', '.join(set(skill_names))})")

        return "\n".join(parts)
