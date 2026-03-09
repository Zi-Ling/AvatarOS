# app/avatar/runtime/reference_resolver.py
"""
ReferenceResolver — 运行时指代消解层（第一层）

职责：在 Planner 之前，把用户 goal 里的跨轮引用（"这首诗"、"那个文件"、"上次结果"）
绑定到结构化来源，生成带 source_type、confidence 的 resolved_inputs。

优先级链（高 → 低）：
  1. task_result metadata  — output_path / output_value（最可信，结构化）
  2. chat assistant content — 最近一条 chat 类型 assistant 消息（文本内容）
  3. 无来源                 — 返回空，触发 clarification/fallback

typed candidates 设计：
  - 每个 ResolvedInput 带 ref_type: "content" | "path" | "both"
  - ReferenceResolution 暴露 content_ref / path_ref 两个快捷属性
  - to_env_dict() 按类型分组输出，ParamBinder 精确取对应候选
  - 多引用共存：同一轮可同时有 content_ref 和 path_ref（来自不同来源）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# UI 前缀清洗：去掉 ✅ ❌ ⚠️ 等 emoji 前缀行和 markdown image block
_UI_PREFIX_RE = re.compile(r'^[✅❌⚠️💡📊\s]*', re.UNICODE)
_IMAGE_BLOCK_RE = re.compile(r'```image\n.*?\n```', re.DOTALL)
_TRUNCATION_MARKER = "...[truncated]"

RefType = Literal["content", "path", "both"]


@dataclass
class ResolvedInput:
    """单个绑定结果"""
    source_type: str          # "task_result" | "chat_message"
    source_id: str            # message index or task_id
    resolver_rule: str        # 触发的规则描述
    confidence: float         # 0.0 ~ 1.0
    ref_type: RefType = "content"          # 引用类型：content / path / both
    content: Optional[str] = None          # 文本内容
    file_path: Optional[str] = None        # 文件路径


@dataclass
class ReferenceResolution:
    """ReferenceResolver 的输出"""
    resolved: bool = False
    inputs: list[ResolvedInput] = field(default_factory=list)

    @property
    def best(self) -> Optional[ResolvedInput]:
        """返回置信度最高的绑定"""
        return max(self.inputs, key=lambda x: x.confidence) if self.inputs else None

    @property
    def content_ref(self) -> Optional[ResolvedInput]:
        """返回最佳 content 类型引用（ref_type in content/both）"""
        candidates = [r for r in self.inputs if r.ref_type in ("content", "both") and r.content]
        return max(candidates, key=lambda x: x.confidence) if candidates else None

    @property
    def path_ref(self) -> Optional[ResolvedInput]:
        """返回最佳 path 类型引用（ref_type in path/both）"""
        candidates = [r for r in self.inputs if r.ref_type in ("path", "both") and r.file_path]
        return max(candidates, key=lambda x: x.confidence) if candidates else None

    def to_env_dict(self) -> dict:
        """
        转换为注入 env_context 的格式。

        typed 输出：
          content_ref  — 最佳 content 候选（confidence, source_type, content）
          path_ref     — 最佳 path 候选（confidence, source_type, file_path）

        兼容旧字段（best 候选的扁平展开）：
          confidence, source_type, source_id, resolver_rule, content, file_path
        """
        if not self.inputs:
            return {}

        result: dict = {}

        # typed refs
        cr = self.content_ref
        if cr:
            result["content_ref"] = {
                "confidence": cr.confidence,
                "source_type": cr.source_type,
                "source_id": cr.source_id,
                "resolver_rule": cr.resolver_rule,
                "content": cr.content,
            }

        pr = self.path_ref
        if pr:
            result["path_ref"] = {
                "confidence": pr.confidence,
                "source_type": pr.source_type,
                "source_id": pr.source_id,
                "resolver_rule": pr.resolver_rule,
                "file_path": pr.file_path,
            }

        # 兼容旧字段：用 best 候选扁平展开（ParamBinder / Planner 旧代码仍可用）
        b = self.best
        result.update({
            "source_type": b.source_type,
            "source_id": b.source_id,
            "resolver_rule": b.resolver_rule,
            "confidence": b.confidence,
        })
        if b.content:
            result["content"] = b.content
        if b.file_path:
            result["file_path"] = b.file_path

        return result


def _clean_content(raw: str) -> str:
    """清洗 UI 前缀、image block、截断标记"""
    text = _IMAGE_BLOCK_RE.sub("", raw).strip()
    lines = text.splitlines()
    if lines:
        first = _UI_PREFIX_RE.sub("", lines[0]).strip()
        if first:
            lines[0] = first
        elif len(lines) > 1:
            lines = lines[1:]
    return "\n".join(lines).strip()


class ReferenceResolver:
    """
    无状态解析器，每次请求独立调用。

    resolve(history) 按优先级扫描 history，返回 ReferenceResolution。
    调用方无需传入 goal 或指代词——只要有 history 就尝试绑定，
    由 confidence 决定是否使用（建议阈值 0.5）。
    """

    # 置信度配置
    CONFIDENCE_TASK_RESULT_FULL = 0.95   # task_result 有 path + value
    CONFIDENCE_TASK_RESULT_PATH = 0.85   # task_result 只有 path
    CONFIDENCE_TASK_RESULT_VALUE = 0.80  # task_result 只有 value
    CONFIDENCE_CHAT_MESSAGE = 0.65       # chat assistant 消息

    # 内容截断上限
    MAX_CONTENT_LEN = 2000

    def resolve(self, history: list) -> ReferenceResolution:
        """
        从 history 里按优先级提取最可信的引用绑定。
        history 格式：[{"role": "user"|"assistant", "content": "...", "metadata": {...}}, ...]
        """
        resolution = ReferenceResolution()

        for idx, msg in enumerate(reversed(history)):
            if msg.get("role") != "assistant":
                continue

            meta = msg.get("metadata") or {}
            msg_type = meta.get("message_type", "chat")

            if msg_type == "task_result":
                ri = self._from_task_result(meta, idx)
                if ri:
                    resolution.inputs.append(ri)
                    resolution.resolved = True
                    logger.debug(
                        f"[ReferenceResolver] Bound from task_result "
                        f"(ref_type={ri.ref_type}, confidence={ri.confidence:.2f})"
                    )
                    return resolution

            elif msg_type == "chat":
                content = msg.get("content", "")
                if content:
                    cleaned = _clean_content(content)
                    # 跳过无实质内容的状态消息（如"⚙️ 正在规划任务..."、"💡 ..."等）
                    # 这类消息是 task ack，不是可引用的内容
                    if len(cleaned) < 20:
                        continue
                    ri = self._from_chat_message(content, idx)
                    resolution.inputs.append(ri)
                    resolution.resolved = True
                    logger.debug(
                        f"[ReferenceResolver] Bound from chat message "
                        f"(ref_type={ri.ref_type}, confidence={ri.confidence:.2f})"
                    )
                    return resolution

        return resolution

    def _from_task_result(self, meta: dict, idx: int) -> Optional[ResolvedInput]:
        file_path = meta.get("output_path") or ""
        raw_value = meta.get("output_value") or ""
        task_id = meta.get("task_id", f"msg_{idx}")

        if not file_path and not raw_value:
            return None

        content = raw_value[:self.MAX_CONTENT_LEN] if raw_value else None

        if file_path and content:
            confidence = self.CONFIDENCE_TASK_RESULT_FULL
            rule = "task_result.output_path+output_value"
            ref_type: RefType = "both"
        elif file_path:
            confidence = self.CONFIDENCE_TASK_RESULT_PATH
            rule = "task_result.output_path"
            ref_type = "path"
        else:
            confidence = self.CONFIDENCE_TASK_RESULT_VALUE
            rule = "task_result.output_value"
            ref_type = "content"

        return ResolvedInput(
            source_type="task_result",
            source_id=task_id,
            resolver_rule=rule,
            confidence=confidence,
            ref_type=ref_type,
            content=content,
            file_path=file_path or None,
        )

    def _from_chat_message(self, raw_content: str, idx: int) -> ResolvedInput:
        cleaned = _clean_content(raw_content)
        if len(cleaned) > self.MAX_CONTENT_LEN:
            cleaned = cleaned[:self.MAX_CONTENT_LEN] + _TRUNCATION_MARKER

        return ResolvedInput(
            source_type="chat_message",
            source_id=f"msg_{idx}",
            resolver_rule="chat_message.assistant_content",
            confidence=self.CONFIDENCE_CHAT_MESSAGE,
            ref_type="content",
            content=cleaned,
        )
