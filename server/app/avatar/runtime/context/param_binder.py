# app/avatar/runtime/param_binder.py
"""
ParamBinder — 确定性参数绑定层（第三层）

职责：在 Planner 选定 skill 并生成节点之后、节点执行之前，
把 resolved_inputs 里的结构化数据直接绑定到节点参数的空槽位。

绑定策略（skill schema 驱动）：
  - 从 skill registry 读取参数的 description 字段
  - 按 description 里的语义关键词判断参数类型（content_like / path_like）
  - 优先使用 typed refs（content_ref / path_ref）精确匹配，兜底用扁平字段
  - 只填充 Planner 留空（None / ""）的必填槽位
  - 每次绑定记录 binding_log，可审计

激活条件（缺失槽位驱动）：
  - 只有当 skill 存在未满足的必填参数时才激活绑定
  - 避免在无关 skill 上过度绑定（如 net.get、python.run 等）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 语义关键词：从参数 description 里识别参数类型
_CONTENT_KEYWORDS = {
    "content", "text", "body", "message", "data", "write",
    "内容", "文本", "正文", "写入",
}
_PATH_KEYWORDS = {
    "path", "file", "destination", "target", "output", "save",
    "路径", "文件", "目标", "保存",
}
_SOURCE_PATH_KEYWORDS = {
    "source", "from", "input file", "src",
    "来源", "源文件",
}


def _classify_param(param_name: str, param_schema: dict) -> Optional[str]:
    """
    从参数 schema 的 description 和参数名判断语义类型。
    返回 "content" | "path" | "source_path" | None
    """
    description = (param_schema.get("description") or "").lower()
    name_lower = param_name.lower()
    combined = description + " " + name_lower

    if any(kw in combined for kw in _PATH_KEYWORDS):
        if any(kw in combined for kw in _SOURCE_PATH_KEYWORDS):
            return "source_path"
        return "path"

    if any(kw in combined for kw in _CONTENT_KEYWORDS):
        return "content"

    return None


def _get_skill_schema(skill_name: str) -> dict:
    """从 skill registry 获取参数 schema，失败时返回空 dict"""
    try:
        from app.avatar.skills.registry import skill_registry
        skill_cls = skill_registry.get(skill_name)
        if not skill_cls or not skill_cls.spec.input_model:
            return {}
        json_schema = skill_cls.spec.input_model.model_json_schema()
        return {
            "properties": json_schema.get("properties", {}),
            "required": json_schema.get("required", []),
        }
    except Exception as e:
        logger.debug(f"[ParamBinder] Failed to get schema for {skill_name}: {e}")
        return {}


def has_unfilled_required_params(skill_name: str, params: dict) -> bool:
    """
    检查 skill 是否存在未满足的必填参数。
    只有存在未满足必填参数时，才值得激活绑定。
    """
    schema = _get_skill_schema(skill_name)
    required = schema.get("required", [])
    if not required:
        return False

    for param in required:
        val = params.get(param)
        if val in (None, "", [], {}):
            return True
    return False


def bind_params(
    skill_name: str,
    params: dict,
    resolved_inputs: dict,
    confidence_threshold: float = 0.5,
) -> tuple[dict, list[dict]]:
    """
    把 resolved_inputs 绑定到 params 的空必填槽位。

    typed refs 优先：
      - content 类参数 → resolved_inputs["content_ref"]["content"]
      - path 类参数    → resolved_inputs["path_ref"]["file_path"]
    兜底：
      - 旧扁平字段 resolved_inputs["content"] / resolved_inputs["file_path"]

    Args:
        skill_name: skill 名称
        params: Planner 生成的原始参数 dict（会被复制，不修改原始）
        resolved_inputs: ReferenceResolution.to_env_dict() 的输出
        confidence_threshold: 低于此置信度不绑定

    Returns:
        (bound_params, binding_log)
    """
    if not resolved_inputs:
        return params, []

    # 激活条件：只有存在未满足必填参数时才绑定
    if not has_unfilled_required_params(skill_name, params):
        logger.debug(f"[ParamBinder] Skipping {skill_name}: no unfilled required params")
        return params, []

    schema = _get_skill_schema(skill_name)
    properties = schema.get("properties", {})

    bound = dict(params)
    binding_log = []

    # 提取 typed refs（优先）和兜底扁平字段
    content_ref = resolved_inputs.get("content_ref") or {}
    path_ref = resolved_inputs.get("path_ref") or {}

    # 兜底扁平字段（旧格式兼容）
    flat_content = resolved_inputs.get("content")
    flat_file_path = resolved_inputs.get("file_path")
    flat_confidence = resolved_inputs.get("confidence", 0.0)
    flat_source_type = resolved_inputs.get("source_type", "unknown")
    flat_resolver_rule = resolved_inputs.get("resolver_rule", "unknown")

    for param_name, current_val in params.items():
        # 只填充空槽位
        if current_val not in (None, "", [], {}):
            continue

        param_schema = properties.get(param_name, {})
        semantic_type = _classify_param(param_name, param_schema)

        if semantic_type == "content":
            # 优先 typed content_ref
            if content_ref and content_ref.get("confidence", 0) >= confidence_threshold and content_ref.get("content"):
                bound[param_name] = content_ref["content"]
                binding_log.append({
                    "param": param_name,
                    "semantic_type": "content",
                    "source": content_ref.get("source_type", "unknown"),
                    "rule": content_ref.get("resolver_rule", "content_ref"),
                    "confidence": content_ref["confidence"],
                    "via": "content_ref",
                })
                logger.info(
                    f"[ParamBinder] {skill_name}.{param_name} ← content_ref "
                    f"(source={content_ref.get('source_type')}, confidence={content_ref['confidence']:.2f})"
                )
            # 兜底扁平字段
            elif flat_content and flat_confidence >= confidence_threshold:
                bound[param_name] = flat_content
                binding_log.append({
                    "param": param_name,
                    "semantic_type": "content",
                    "source": flat_source_type,
                    "rule": flat_resolver_rule,
                    "confidence": flat_confidence,
                    "via": "flat",
                })
                logger.info(
                    f"[ParamBinder] {skill_name}.{param_name} ← content(flat) "
                    f"(source={flat_source_type}, confidence={flat_confidence:.2f})"
                )

        elif semantic_type in ("path", "source_path"):
            # 优先 typed path_ref
            if path_ref and path_ref.get("confidence", 0) >= confidence_threshold and path_ref.get("file_path"):
                bound[param_name] = path_ref["file_path"]
                binding_log.append({
                    "param": param_name,
                    "semantic_type": semantic_type,
                    "source": path_ref.get("source_type", "unknown"),
                    "rule": path_ref.get("resolver_rule", "path_ref"),
                    "confidence": path_ref["confidence"],
                    "via": "path_ref",
                })
                logger.info(
                    f"[ParamBinder] {skill_name}.{param_name} ← path_ref "
                    f"(source={path_ref.get('source_type')}, confidence={path_ref['confidence']:.2f})"
                )
            # 兜底扁平字段
            elif flat_file_path and flat_confidence >= confidence_threshold:
                bound[param_name] = flat_file_path
                binding_log.append({
                    "param": param_name,
                    "semantic_type": semantic_type,
                    "source": flat_source_type,
                    "rule": flat_resolver_rule,
                    "confidence": flat_confidence,
                    "via": "flat",
                })
                logger.info(
                    f"[ParamBinder] {skill_name}.{param_name} ← file_path(flat) "
                    f"(source={flat_source_type}, confidence={flat_confidence:.2f})"
                )

    return bound, binding_log
