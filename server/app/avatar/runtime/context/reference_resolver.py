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


@dataclass
class ResolverConfig:
    """All tunable parameters for ReferenceResolver in one place.

    Centralises thresholds, confidence scores, and limits that were
    previously scattered as magic numbers across multiple methods.
    """
    # ── Confidence scores ───────────────────────────────────────────
    confidence_task_result_full: float = 0.95   # task_result with path + value
    confidence_task_result_path: float = 0.85   # task_result with path only
    confidence_task_result_value: float = 0.80  # task_result with value only
    confidence_chat_message: float = 0.65       # chat assistant message

    # ── Relevance scoring ───────────────────────────────────────────
    relevance_min_confidence: float = 0.40      # below this → skip binding
    relevance_demoted_confidence: float = 0.30  # assigned when demoting
    jaccard_threshold_task: float = 0.15        # task_result relevance cutoff
    jaccard_threshold_chat: float = 0.10        # chat_message relevance cutoff

    # ── Content limits ──────────────────────────────────────────────
    max_content_len: int = 2000
    min_chat_content_len: int = 20              # skip very short chat msgs


class ReferenceResolver:
    """
    无状态解析器，每次请求独立调用。

    resolve(history) 按优先级扫描 history，返回 ReferenceResolution。
    调用方无需传入 goal 或指代词——只要有 history 就尝试绑定，
    由 confidence 决定是否使用（建议阈值 0.5）。

    设计原则：
    - 默认允许绑定（default-allow），只在明确是独立新任务时阻断
    - 所有阈值集中在 ResolverConfig，不散落在方法里
    - 正则模式只做粗粒度分类，精细判断靠 token 重叠度
    """

    def __init__(self, config: Optional[ResolverConfig] = None):
        self.config = config or ResolverConfig()

    # ── Backward-compatible class-level aliases ─────────────────────
    # Existing callers may read these; delegate to config.
    @property
    def CONFIDENCE_TASK_RESULT_FULL(self) -> float:
        return self.config.confidence_task_result_full

    @property
    def CONFIDENCE_TASK_RESULT_PATH(self) -> float:
        return self.config.confidence_task_result_path

    @property
    def CONFIDENCE_TASK_RESULT_VALUE(self) -> float:
        return self.config.confidence_task_result_value

    @property
    def CONFIDENCE_CHAT_MESSAGE(self) -> float:
        return self.config.confidence_chat_message

    @property
    def MAX_CONTENT_LEN(self) -> int:
        return self.config.max_content_len

    def resolve(self, history: list, goal: str = "") -> ReferenceResolution:
        """
        从 history 里按优先级提取最可信的引用绑定。

        设计原则（default-allow）：
        - 默认允许跨轮绑定
        - 只在 goal 明确是独立新任务时才阻断 chat_message 绑定
        - task_result 绑定不受阻断，仅通过 relevance scoring 降权
        - 所有阈值来自 self.config，不在方法体内硬编码
        """
        resolution = ReferenceResolution()
        cfg = self.config

        # ── Chat-message binding gate (default-allow) ───────────────────
        # BLOCK chat binding only when goal is clearly an independent new
        # task AND has no cross-turn indicators. Everything else defaults
        # to "allow" — short supplementary messages, constraint additions,
        # corrections all naturally get cross-turn context.
        _skip_chat = self._is_independent_new_task(goal)

        for idx, msg in enumerate(reversed(history)):
            if msg.get("role") != "assistant":
                continue

            meta = msg.get("metadata") or {}
            msg_type = meta.get("message_type", "chat")

            if msg_type == "task_result":
                ri = self._from_task_result(meta, idx)
                if ri is None:
                    continue
                if goal and ri.confidence > cfg.relevance_min_confidence:
                    ri.confidence = self._adjust_confidence_by_relevance(
                        ri, goal, meta,
                    )
                if ri.confidence < cfg.relevance_min_confidence:
                    logger.debug(
                        "[ReferenceResolver] Skipping irrelevant task_result "
                        "(confidence=%.2f after relevance check)", ri.confidence,
                    )
                    continue
                resolution.inputs.append(ri)
                resolution.resolved = True
                logger.debug(
                    "[ReferenceResolver] Bound from task_result "
                    "(ref_type=%s, confidence=%.2f)", ri.ref_type, ri.confidence,
                )
                return resolution

            elif msg_type == "chat":
                if _skip_chat:
                    logger.debug(
                        "[ReferenceResolver] Skipping chat_message binding — "
                        "goal is an independent new task",
                    )
                    continue

                content = msg.get("content", "")
                if not content:
                    continue
                cleaned = _clean_content(content)
                if len(cleaned) < cfg.min_chat_content_len:
                    continue
                ri = self._from_chat_message(content, idx)
                if ri is None:
                    continue

                # Relevance check for chat messages
                if goal and not self._is_relevant_chat(goal, cleaned, cfg.jaccard_threshold_chat):
                    continue

                resolution.inputs.append(ri)
                resolution.resolved = True
                logger.debug(
                    "[ReferenceResolver] Bound from chat message "
                    "(ref_type=%s, confidence=%.2f)", ri.ref_type, ri.confidence,
                )
                return resolution

        return resolution

    # ── Binding gate ────────────────────────────────────────────────────

    def _is_independent_new_task(self, goal: str) -> bool:
        """Determine if goal is clearly an independent new task.

        Uses a structural heuristic: goal starts with a creation/action verb
        AND does not contain cross-turn reference indicators.

        Returns True → skip chat_message binding.
        Returns False → allow chat_message binding (default).
        """
        if not goal:
            return False
        stripped = goal.strip()
        # Structural check: starts with a creation/generation verb
        if not self._NEW_TASK_HEAD_RE.search(stripped):
            return False
        # Override: explicit cross-turn reference → not independent
        if self._CROSS_TURN_RE.search(goal):
            return False
        return True

    # Structural pattern: goal starts with a creation/generation/action verb.
    # This is intentionally broad — false positives are safe because the
    # downstream relevance scoring will still allow binding if the content
    # is actually related.
    _NEW_TASK_HEAD_RE = re.compile(
        # Chinese: verb + quantifier/object at start of sentence
        r'^(写[一首篇段个]|生成|创建|搜索|查[找询]|计算|画[一个]?|'
        r'做[一个]?|列出|翻译[一这]|打开|启动|运行|下载|安装|删除|'
        r'发送|上传|编写|设计|分析|总结|整理|'
        # English: verb at start
        r'write\s+a\b|create\s+|generate\s+|search\s+|find\s+|'
        r'calculate\s+|draw\s+|make\s+|list\s+|compose\s+|'
        r'open\s+|launch\s+|run\s+|download\s+|install\s+|'
        r'delete\s+|send\s+|upload\s+|build\s+|design\s+)',
        re.IGNORECASE,
    )

    # Cross-turn reference indicators: user explicitly refers to previous
    # turn's result. Presence overrides _NEW_TASK_HEAD_RE.
    _CROSS_TURN_RE = re.compile(
        r'(这首|那个|上次|刚才|之前|上面的|前面的|'
        r'the\s+result|that\s+file|this\s+poem|the\s+text|'
        r'last\s+result|previous|the\s+output)',
        re.IGNORECASE,
    )

    # ── Relevance scoring ───────────────────────────────────────────────

    def _is_relevant_chat(self, goal: str, chat_text: str, threshold: float) -> bool:
        """Check if chat_text is relevant to goal via token overlap."""
        goal_tokens = self._extract_tokens(goal)
        chat_tokens = self._extract_tokens(chat_text[:200])
        if not goal_tokens or not chat_tokens:
            return True  # can't determine → allow
        jaccard = len(goal_tokens & chat_tokens) / len(goal_tokens | chat_tokens)
        if jaccard < threshold:
            logger.debug(
                "[ReferenceResolver] Skipping irrelevant chat_message "
                "(jaccard=%.2f < %.2f)", jaccard, threshold,
            )
            return False
        return True

    def _adjust_confidence_by_relevance(
        self, ri: ResolvedInput, goal: str, meta: dict,
    ) -> float:
        """Adjust confidence based on goal↔previous-task semantic overlap.

        Strategy:
        1. Explicit cross-turn reference → keep original confidence
        2. Independent new task → demote to config.relevance_demoted_confidence
        3. Otherwise → Jaccard overlap scoring, demote if below threshold
        """
        cfg = self.config

        if self._CROSS_TURN_RE.search(goal):
            return ri.confidence

        if self._is_independent_new_task(goal):
            logger.debug(
                "[ReferenceResolver] Independent task detected, "
                "demoting confidence %.2f → %.2f",
                ri.confidence, cfg.relevance_demoted_confidence,
            )
            return cfg.relevance_demoted_confidence

        # Token overlap with previous task's goal or content
        prev_text = (
            meta.get("goal") or meta.get("task_goal") or
            (ri.content or "")[:200]
        )
        if not prev_text:
            return ri.confidence

        goal_tokens = self._extract_tokens(goal)
        prev_tokens = self._extract_tokens(prev_text)
        if not goal_tokens or not prev_tokens:
            return ri.confidence

        jaccard = len(goal_tokens & prev_tokens) / len(goal_tokens | prev_tokens)
        if jaccard < cfg.jaccard_threshold_task:
            logger.debug(
                "[ReferenceResolver] Cross-turn relevance low "
                "(jaccard=%.2f < %.2f), demoting confidence %.2f → %.2f",
                jaccard, cfg.jaccard_threshold_task,
                ri.confidence, cfg.relevance_demoted_confidence,
            )
            return cfg.relevance_demoted_confidence

        return ri.confidence

    # ── Source extractors ───────────────────────────────────────────────

    def _from_task_result(self, meta: dict, idx: int) -> Optional[ResolvedInput]:
        file_path = meta.get("output_path") or ""
        task_id = meta.get("task_id", f"msg_{idx}")

        if file_path:
            try:
                from app.avatar.runtime.workspace.path_canonical import is_container_path
                is_container_path(file_path)  # validate; no-op if not container
            except ImportError:
                pass

        raw_value = meta.get("output_value_full") or meta.get("output_value") or ""
        artifact_ref = meta.get("artifact_ref")

        if not file_path and not raw_value and not artifact_ref:
            return None

        if raw_value and _is_binary_like_payload(raw_value):
            logger.debug(
                "[ReferenceResolver] task_result output_value is binary-like "
                "(%d chars), skipping content binding", len(raw_value),
            )
            raw_value = ""

        content = raw_value[:self.config.max_content_len] if raw_value else None

        if file_path and content:
            confidence = self.config.confidence_task_result_full
            rule, ref_type = "task_result.output_path+output_value", "both"
        elif file_path:
            confidence = self.config.confidence_task_result_path
            rule, ref_type = "task_result.output_path", "path"
        elif content:
            confidence = self.config.confidence_task_result_value
            rule, ref_type = "task_result.output_value", "content"
        elif artifact_ref:
            confidence = self.config.confidence_task_result_path
            rule, ref_type = "task_result.artifact_ref", "path"
        else:
            return None

        return ResolvedInput(
            source_type="task_result", source_id=task_id,
            resolver_rule=rule, confidence=confidence,
            ref_type=ref_type, content=content,
            file_path=file_path or None, artifact_ref=artifact_ref,
        )

    def _from_chat_message(self, raw_content: str, idx: int) -> Optional[ResolvedInput]:
        cleaned = _clean_content(raw_content)
        if _is_binary_like_payload(cleaned):
            logger.debug(
                "[ReferenceResolver] chat message is binary-like "
                "(%d chars), skipping", len(cleaned),
            )
            return None
        if len(cleaned) > self.config.max_content_len:
            cleaned = cleaned[:self.config.max_content_len] + _TRUNCATION_MARKER
        return ResolvedInput(
            source_type="chat_message", source_id=f"msg_{idx}",
            resolver_rule="chat_message.assistant_content",
            confidence=self.config.confidence_chat_message,
            ref_type="content", content=cleaned,
        )

    # ── Token extraction ────────────────────────────────────────────────

    # Stopwords: high-frequency function words that add noise to Jaccard.
    # Kept as a class-level frozenset for reuse across calls.
    _STOP_WORDS: frozenset = frozenset({
        # English function words
        "the", "this", "that", "and", "for", "with", "from", "into",
        "is", "are", "was", "were", "be", "to", "of", "in", "on",
        "at", "by", "an", "it", "as", "or", "if", "do", "no",
        # Chinese function words (2+ chars to match extraction pattern)
        "没有", "可以", "自己", "一个", "一首", "一段", "一篇",
        "关于", "帮我", "请你", "什么", "怎么", "这个", "那个",
    })

    @staticmethod
    def _extract_tokens(text: str) -> set:
        """Extract keyword tokens for lightweight similarity scoring.

        Chinese: contiguous CJK sequences (2+ chars).
        English: contiguous alpha sequences (2+ chars), lowercased.
        Single-char Chinese tokens are excluded — too noisy for Jaccard.
        """
        raw = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{2,}', text.lower())
        return {t for t in raw if t not in ReferenceResolver._STOP_WORDS}


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
