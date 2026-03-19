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
    artifact_ref: Optional[str] = None     # 大型内容的 artifact_id 引用


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
            path_entry = {
                "confidence": pr.confidence,
                "source_type": pr.source_type,
                "source_id": pr.source_id,
                "resolver_rule": pr.resolver_rule,
                "file_path": pr.file_path,
            }
            if pr.artifact_ref:
                path_entry["artifact_ref"] = pr.artifact_ref
            result["path_ref"] = path_entry

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
        if b.artifact_ref:
            result["artifact_ref"] = b.artifact_ref

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


# 可引用内容的最小语义密度阈值：非 hex/base64 字符占比必须超过此值
_MIN_SEMANTIC_RATIO = 0.15
# 超过此长度才做 binary-like 检测（短字符串不做）
_BINARY_DETECT_MIN_LEN = 64

_BASE64_RE = re.compile(r'^[A-Za-z0-9+/\n]+=*$')


def _is_binary_like_payload(text: str) -> bool:
    """
    判断字符串是否为 binary-like payload（不适合作为 content_ref 注入 prompt）。

    覆盖：
    - 纯 hex 字符串（PNG/JPEG/任意二进制的 hex 编码）
    - 纯 base64 字符串
    - 低语义密度文本（非字母数字字符占比极低，如压缩编码、机器中间产物）

    不覆盖：
    - 正常自然语言文本
    - 短字符串（< _BINARY_DETECT_MIN_LEN）
    - 结构化但可读的 JSON / CSV（有空格、标点、换行）
    """
    stripped = text.strip()
    if len(stripped) < _BINARY_DETECT_MIN_LEN:
        return False

    # 规则 1：纯 hex（去掉空白后全是 0-9a-fA-F）
    no_ws = "".join(stripped.split())
    if re.fullmatch(r'[0-9a-fA-F]+', no_ws):
        return True

    # 规则 2：纯 base64（去掉换行后全是 base64 字符集 + padding）
    no_nl = stripped.replace("\n", "").replace("\r", "")
    if len(no_nl) > _BINARY_DETECT_MIN_LEN and _BASE64_RE.fullmatch(no_nl):
        return True

    # 规则 3：低语义密度——空格+标点+换行占比极低（< _MIN_SEMANTIC_RATIO）
    # 正常自然语言/JSON/CSV 里空格和标点很多；机器编码串几乎没有
    semantic_chars = sum(1 for c in stripped if c in ' \t\n\r.,;:!?()[]{}"\'-_/\\')
    ratio = semantic_chars / len(stripped)
    if ratio < _MIN_SEMANTIC_RATIO and len(stripped) > 200:
        return True

    return False


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

    def resolve(self, history: list, goal: str = "") -> ReferenceResolution:
        """
        从 history 里按优先级提取最可信的引用绑定。
        history 格式：[{"role": "user"|"assistant", "content": "...", "metadata": {...}}, ...]

        goal: 当前任务的 goal 文本。如果提供，会做轻量级语义相关性检测，
        对无关的上一轮结果降低 confidence，避免跨轮过度绑定。
        """
        resolution = ReferenceResolution()

        # 绑定必要性门：如果 goal 没有跨轮指代词且是独立任务，不绑定 chat_message
        _needs_cross_turn = bool(
            goal and self._CROSS_TURN_INDICATORS.search(goal)
        )

        for idx, msg in enumerate(reversed(history)):
            if msg.get("role") != "assistant":
                continue

            meta = msg.get("metadata") or {}
            msg_type = meta.get("message_type", "chat")

            if msg_type == "task_result":
                ri = self._from_task_result(meta, idx)
                if ri:
                    # Goal-aware relevance check: if the current goal has no
                    # keyword overlap with the previous task result, this is
                    # likely an unrelated cross-turn binding. Demote confidence
                    # so downstream won't use it.
                    if goal and ri.confidence > 0.4:
                        ri.confidence = self._adjust_confidence_by_relevance(
                            ri, goal, meta
                        )
                    if ri.confidence < 0.4:
                        logger.debug(
                            f"[ReferenceResolver] Skipping irrelevant task_result "
                            f"(confidence={ri.confidence:.2f} after relevance check)"
                        )
                        continue
                    resolution.inputs.append(ri)
                    resolution.resolved = True
                    logger.debug(
                        f"[ReferenceResolver] Bound from task_result "
                        f"(ref_type={ri.ref_type}, confidence={ri.confidence:.2f})"
                    )
                    return resolution

            elif msg_type == "chat":
                # 绑定必要性门：chat_message 只在有明确跨轮指代词时才绑定
                # 避免独立任务（如"生成 people.json"）被上一轮 chat 内容污染
                if not _needs_cross_turn:
                    logger.debug(
                        "[ReferenceResolver] Skipping chat_message binding — "
                        "no cross-turn indicator in goal"
                    )
                    continue

                content = msg.get("content", "")
                if content:
                    cleaned = _clean_content(content)
                    if len(cleaned) < 20:
                        continue
                    ri = self._from_chat_message(content, idx)
                    if ri is None:
                        continue  # binary-like，跳过继续找下一条

                    # chat_message 也做 goal 相关性检查
                    if goal:
                        goal_tokens = self._extract_tokens(goal)
                        chat_tokens = self._extract_tokens(cleaned[:200])
                        if goal_tokens and chat_tokens:
                            overlap = goal_tokens & chat_tokens
                            union = goal_tokens | chat_tokens
                            jaccard = len(overlap) / len(union) if union else 0.0
                            if jaccard < 0.1:
                                logger.debug(
                                    f"[ReferenceResolver] Skipping irrelevant chat_message "
                                    f"(jaccard={jaccard:.2f})"
                                )
                                continue

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
        task_id = meta.get("task_id", f"msg_{idx}")

        # 路径规范化：确保 file_path 是宿主机路径
        if file_path:
            try:
                from app.avatar.runtime.workspace.path_canonical import (
                    canonicalize_path, is_container_path,
                )
                if is_container_path(file_path):
                    # 无法在此处获取 host_workspace，保留容器路径
                    # （调用方应在注入 env_context 前已规范化）
                    pass
            except ImportError:
                pass

        # 优先使用完整值（小型值对象），fallback 到截断展示值
        raw_value = meta.get("output_value_full") or meta.get("output_value") or ""
        artifact_ref = meta.get("artifact_ref")

        if not file_path and not raw_value and not artifact_ref:
            return None

        # binary-like payload（hex/base64/低语义密度）不作为可引用内容
        # 只保留 file_path（如果有），让 LLM 通过路径引用而非内联原始值
        value_is_binary = raw_value and _is_binary_like_payload(raw_value)
        if value_is_binary:
            logger.debug(
                f"[ReferenceResolver] task_result output_value is binary-like payload "
                f"({len(raw_value)} chars), skipping content binding"
            )
            raw_value = ""  # 不生成 content_ref

        content = raw_value[:self.MAX_CONTENT_LEN] if raw_value else None

        if file_path and content:
            confidence = self.CONFIDENCE_TASK_RESULT_FULL
            rule = "task_result.output_path+output_value"
            ref_type: RefType = "both"
        elif file_path:
            confidence = self.CONFIDENCE_TASK_RESULT_PATH
            rule = "task_result.output_path"
            ref_type = "path"
        elif content:
            confidence = self.CONFIDENCE_TASK_RESULT_VALUE
            rule = "task_result.output_value"
            ref_type = "content"
        elif artifact_ref:
            # 大型内容只有 artifact 引用，没有内联值
            confidence = self.CONFIDENCE_TASK_RESULT_PATH
            rule = "task_result.artifact_ref"
            ref_type = "path"
        else:
            # 既没有可用 path 也没有可用 content（binary 被过滤且无 path）
            return None

        return ResolvedInput(
            source_type="task_result",
            source_id=task_id,
            resolver_rule=rule,
            confidence=confidence,
            ref_type=ref_type,
            content=content,
            file_path=file_path or None,
            artifact_ref=artifact_ref,
        )

    def _from_chat_message(self, raw_content: str, idx: int) -> Optional[ResolvedInput]:
        cleaned = _clean_content(raw_content)

        # binary-like payload 不作为可引用内容，直接跳过
        if _is_binary_like_payload(cleaned):
            logger.debug(
                f"[ReferenceResolver] chat message is binary-like payload "
                f"({len(cleaned)} chars), skipping content binding"
            )
            return None

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

    # 跨轮引用指代词：用户明确引用上一轮结果的关键词
    _CROSS_TURN_INDICATORS = re.compile(
        r'(这首|那个|上次|刚才|之前|the\s+result|that\s+file|this\s+poem|'
        r'the\s+text|上面的|前面的|last\s+result|previous)',
        re.IGNORECASE,
    )

    def _adjust_confidence_by_relevance(
        self,
        ri: ResolvedInput,
        goal: str,
        meta: dict,
    ) -> float:
        """
        根据当前 goal 和上一轮 task_result 的语义相关性调整 confidence。

        策略：
        1. 如果 goal 里有明确的跨轮指代词 → 保持原 confidence（用户明确引用）
        2. 提取 goal 和上一轮 goal/content 的关键词，计算重叠度
        3. 重叠度极低 → 大幅降低 confidence（避免无关绑定）
        """
        # 用户明确引用上一轮 → 保持原 confidence
        if self._CROSS_TURN_INDICATORS.search(goal):
            return ri.confidence

        # 提取上一轮的 goal（如果有）或 content 的前 200 字符作为比较对象
        prev_goal = meta.get("goal") or meta.get("task_goal") or ""
        prev_text = prev_goal or (ri.content or "")[:200]

        if not prev_text:
            return ri.confidence

        # 轻量级关键词重叠：提取 2+ 字符的 token，计算 Jaccard 相似度
        goal_tokens = self._extract_tokens(goal)
        prev_tokens = self._extract_tokens(prev_text)

        if not goal_tokens or not prev_tokens:
            return ri.confidence

        overlap = goal_tokens & prev_tokens
        union = goal_tokens | prev_tokens
        jaccard = len(overlap) / len(union) if union else 0.0

        if jaccard < 0.1:
            # 几乎无重叠 — 大概率是无关的跨轮绑定
            demoted = 0.30
            logger.debug(
                f"[ReferenceResolver] Cross-turn relevance low "
                f"(jaccard={jaccard:.2f}), demoting confidence "
                f"{ri.confidence:.2f} → {demoted:.2f}"
            )
            return demoted

        return ri.confidence

    @staticmethod
    def _extract_tokens(text: str) -> set:
        """提取文本中的关键词 token（2+ 字符，去停用词）。"""
        # 中文：连续汉字序列；英文：连续字母序列
        raw = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]{2,}', text.lower())
        # 简单停用词过滤
        _stop = {"the", "this", "that", "and", "for", "with", "from", "into",
                 "is", "are", "was", "were", "be", "to", "of", "in", "on",
                 "at", "by", "an", "it", "as", "or", "if", "do", "no",
                 "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
                 "都", "一", "个", "上", "也", "很", "到", "说", "要", "去",
                 "你", "会", "着", "没有", "看", "好", "自己", "这"}
        tokens = set()
        for t in raw:
            if len(t) >= 2 and t not in _stop:
                tokens.add(t)
        return tokens


# ---------------------------------------------------------------------------
# P1: TypedReferenceResolver — type-aware reference binding with policy
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass, field as _field
from typing import Any as _Any, Dict as _Dict, List as _List, Optional as _Optional, Tuple as _Tuple


@_dataclass
class RefBindingPolicy:
    """
    Reference binding policy. All thresholds are configurable — no hardcoded values.
    Defaults are initial suggestions only.
    """
    text_inline_limit: int = 2000           # chars; TEXT content above this is truncated
    json_inline_limit: int = 4096           # bytes; JSON above this → top-level keys only
    binary_inline_allowed: bool = False     # BINARY: never inline, only artifact_id + type
    path_inline_allowed: bool = True        # PATH: inline path string only
    artifact_metadata_only: bool = True     # ARTIFACT: only metadata (id/type/preview/label)
    single_binding_warn_threshold: int = 4096  # tokens; ~10% of typical context window


@_dataclass
class BindingSummaryEntry:
    step_id: str
    value_kind: str
    transport_mode: str
    injected_size: int          # actual bytes injected
    was_truncated: bool
    artifact_id: _Optional[str] = None


class TypedReferenceResolver:
    """
    P1: Enhanced ReferenceResolver with RefBindingPolicy type-aware filtering.

    Prevents binary payloads and oversized content from polluting planner prompts.
    """

    def __init__(
        self,
        policy: _Optional[RefBindingPolicy] = None,
        trace_store: _Optional[_Any] = None,
    ) -> None:
        self.policy = policy or RefBindingPolicy()
        self._trace_store = trace_store

    def resolve_with_policy(
        self,
        outputs: _Dict[str, _Any],
        output_contracts: _Dict[str, _Any],  # step_id → SkillOutputContract
        session_id: str,
    ) -> _Tuple[_Dict[str, _Any], _List[BindingSummaryEntry]]:
        """
        Filter and bind references according to RefBindingPolicy.

        Returns: (filtered_context, binding_summary)

        Rules:
        - BINARY + INLINE → inject only artifact_id and artifact_type
        - TEXT > text_inline_limit → truncate + "[truncated, full content in artifact:{id}]"
        - JSON > json_inline_limit → top-level keys only + artifact_ref
        - PATH → path string only
        - ARTIFACT → metadata only (id, type, preview, semantic_label)
        """
        from app.avatar.runtime.graph.models.output_contract import ValueKind, TransportMode

        filtered: _Dict[str, _Any] = {}
        summary: _List[BindingSummaryEntry] = []

        for step_id, value in outputs.items():
            contract = output_contracts.get(step_id)
            if contract is None:
                # No contract: pass through as-is
                filtered[step_id] = value
                continue

            vk = getattr(contract, "value_kind", None)
            tm = getattr(contract, "transport_mode", None)
            artifact_id = getattr(contract, "artifact_id", None)

            injected, was_truncated = self._apply_policy(
                value=value,
                value_kind=vk,
                transport_mode=tm,
                artifact_id=artifact_id,
                contract=contract,
            )

            injected_size = len(str(injected).encode("utf-8", errors="replace"))
            filtered[step_id] = injected

            entry = BindingSummaryEntry(
                step_id=step_id,
                value_kind=vk.value if vk else "unknown",
                transport_mode=tm.value if tm else "unknown",
                injected_size=injected_size,
                was_truncated=was_truncated,
                artifact_id=artifact_id,
            )
            summary.append(entry)

            # Warn if single binding exceeds threshold
            estimated_tokens = injected_size // 4  # rough estimate
            if estimated_tokens > self.policy.single_binding_warn_threshold:
                self._write_warning_event(session_id, step_id, estimated_tokens)

        return filtered, summary

    def _apply_policy(
        self,
        value: _Any,
        value_kind: _Any,
        transport_mode: _Any,
        artifact_id: _Optional[str],
        contract: _Any,
    ) -> _Tuple[_Any, bool]:
        """Apply binding policy rules. Returns (injected_value, was_truncated)."""
        from app.avatar.runtime.graph.models.output_contract import ValueKind, TransportMode

        # BINARY: never inline
        if value_kind == ValueKind.BINARY:
            return {
                "artifact_id": artifact_id,
                "artifact_type": getattr(contract, "mime_type", "binary"),
            }, False

        # ARTIFACT transport: metadata only
        if transport_mode == TransportMode.ARTIFACT:
            return {
                "artifact_id": artifact_id,
                "artifact_type": getattr(contract, "mime_type", None),
                "semantic_label": getattr(contract, "semantic_label", None),
            }, False

        # PATH: path string only
        if value_kind == ValueKind.PATH:
            path_str = str(value) if value is not None else ""
            return path_str, False

        # TEXT: truncate if over limit
        if value_kind == ValueKind.TEXT:
            text = str(value) if value is not None else ""
            if len(text) > self.policy.text_inline_limit:
                truncated = text[:self.policy.text_inline_limit]
                suffix = f" [truncated, full content in artifact:{artifact_id}]" if artifact_id else " [truncated]"
                return truncated + suffix, True
            return text, False

        # JSON: top-level keys only if over limit
        if value_kind == ValueKind.JSON:
            import json as _json
            try:
                serialized = _json.dumps(value, ensure_ascii=False)
                if len(serialized.encode("utf-8")) > self.policy.json_inline_limit:
                    if isinstance(value, dict):
                        keys_only = {k: "..." for k in value.keys()}
                        ref_info = f" [full JSON in artifact:{artifact_id}]" if artifact_id else ""
                        return {"_keys": list(value.keys()), "_artifact_ref": artifact_id, "_note": f"JSON truncated{ref_info}"}, True
                    return {"_truncated": True, "_artifact_ref": artifact_id}, True
            except Exception:
                pass
            return value, False

        # Default: pass through
        return value, False

    def _write_warning_event(self, session_id: str, step_id: str, token_estimate: int) -> None:
        if not self._trace_store:
            return
        try:
            self._trace_store.record_event(
                session_id=session_id,
                event_type="reference_binding_warning",
                payload={
                    "step_id": step_id,
                    "token_estimate": token_estimate,
                    "threshold": self.policy.single_binding_warn_threshold,
                },
            )
        except Exception:
            pass
