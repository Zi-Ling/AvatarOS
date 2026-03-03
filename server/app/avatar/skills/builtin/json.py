# app/avatar/skills/builtin/json.py

from __future__ import annotations

import os
import json
from typing import Any, Optional, Dict
from pathlib import Path
from pydantic import Field, model_validator

from ..common.path_mixins import PathBindMixin

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


def _get_by_path(obj: Any, path: str) -> Any:
    current = obj
    segments = path.split(".")
    for seg in segments:
        if not seg: continue
        if "[" in seg and seg.endswith("]"):
            name, idx_part = seg.split("[", 1)
            idx = int(idx_part[:-1])
            if name: current = current[name]
            current = current[idx]
        else:
            current = current[seg]
    return current


# ============================================================================
# json.read
# ============================================================================

class JsonReadInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative JSON file path."
    )

    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class JsonReadOutput(SkillOutput):
    path: str
    data: Any

@register_skill
class JsonReadSkill(BaseSkill[JsonReadInput, JsonReadOutput]):
    spec = SkillSpec(
        name="json.read",
        api_name="json.read",
        aliases=["json.load", "file.read_json"],
        description="Read and parse a JSON file. 读取并解析JSON文件。",
        category=SkillCategory.FILE,
        input_model=JsonReadInput,
        output_model=JsonReadOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        synonyms=[
            "load json",
            "parse json",
            "read json file",
            "读取JSON",
            "加载JSON",
            "解析JSON"
        ],
        examples=[
            {"description": "Read JSON file", "params": {"relative_path": "data.json"}}
        ],
        permissions=[SkillPermission(name="file_read", description="Read JSON files")],
        tags=["file", "json", "JSON", "读取", "解析"]
    )

    async def run(self, ctx: SkillContext, params: JsonReadInput) -> JsonReadOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return JsonReadOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).", path="", data=None)

        if ctx.dry_run:
            return JsonReadOutput(success=True, message="[dry_run]", path=str(target_path), data={})

        try:
            if not target_path.exists():
                 return JsonReadOutput(success=False, message="File not found", path=str(target_path), data=None)
            
            text = target_path.read_text(encoding="utf-8")
            obj = json.loads(text)
            return JsonReadOutput(success=True, message="Read JSON", path=str(target_path), data=obj)
        except Exception as e:
             return JsonReadOutput(success=False, message=str(e), path=str(target_path), data=None)


# ============================================================================
# json.write
# ============================================================================

class JsonWriteInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative JSON file path."
    )
    data: Any = Field(..., description="JSON serializable data to write.")
    indent: int = Field(2, description="Indentation level.")

    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class JsonWriteOutput(SkillOutput):
    path: str

@register_skill
class JsonWriteSkill(BaseSkill[JsonWriteInput, JsonWriteOutput]):
    spec = SkillSpec(
        name="json.write",
        api_name="json.write",
        aliases=["json.save", "json.dump", "file.write_json"],
        description="Write a JSON object to a file. 写入JSON数据到文件。",
        category=SkillCategory.FILE,
        input_model=JsonWriteInput,
        output_model=JsonWriteOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="normal"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="file:json",
        artifact_path_field="path",
        
        synonyms=[
            "save json",
            "write json file",
            "dump json",
            "写入JSON",
            "保存JSON",
            "存储JSON"
        ],
        examples=[
            {"description": "Write JSON data", "params": {"relative_path": "output.json", "data": {"key": "value"}}}
        ],
        permissions=[SkillPermission(name="file_write", description="Write JSON files")],
        tags=["file", "json", "JSON", "写入", "保存"]
    )

    async def run(self, ctx: SkillContext, params: JsonWriteInput) -> JsonWriteOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return JsonWriteOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).", path="")

        if ctx.dry_run:
             return JsonWriteOutput(success=True, message="[dry_run]", path=str(target_path))

        try:
            # Pre-execution: Validate data is JSON serializable
            try:
                text = json.dumps(params.data, ensure_ascii=False, indent=params.indent)
            except (TypeError, ValueError) as e:
                return JsonWriteOutput(success=False, message=f"Data is not JSON serializable: {e}", path=str(target_path))
            
            # Execute
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(text, encoding="utf-8")
            
            # Post-execution verification
            if not target_path.exists():
                return JsonWriteOutput(success=False, message="Verification Failed: File not found after write", path=str(target_path))
            
            # Verify file content is valid JSON
            try:
                written_text = target_path.read_text(encoding="utf-8")
                parsed_data = json.loads(written_text)
                
                # Verify data integrity (basic check - compare serialized forms)
                if json.dumps(parsed_data, sort_keys=True) != json.dumps(params.data, sort_keys=True):
                    return JsonWriteOutput(success=False, message="Verification Failed: Written data doesn't match input", path=str(target_path))
                    
            except json.JSONDecodeError as e:
                return JsonWriteOutput(success=False, message=f"Verification Failed: Written file is not valid JSON: {e}", path=str(target_path))
            
            return JsonWriteOutput(success=True, message=f"Written JSON to {target_path.name} ({len(text)} bytes, verified)", path=str(target_path))
        except PermissionError:
            return JsonWriteOutput(success=False, message=f"Permission denied: Cannot write to {target_path}", path=str(target_path))
        except Exception as e:
             return JsonWriteOutput(success=False, message=f"Write failed: {str(e)}", path=str(target_path))


# ============================================================================
# json.extract
# ============================================================================

class JsonExtractInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative JSON file path."
    )
    json_path: str = Field(..., description="Path selector e.g. 'a.b[0]'.")

    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class JsonExtractOutput(SkillOutput):
    path: str
    value: Any

@register_skill
class JsonExtractSkill(BaseSkill[JsonExtractInput, JsonExtractOutput]):
    spec = SkillSpec(
        name="json.extract",
        api_name="json.extract",
        aliases=["json.get", "json.query", "jq"],
        description="Extract value from JSON file using path syntax. 从JSON文件中提取指定路径的值。",
        category=SkillCategory.FILE,
        input_model=JsonExtractInput,
        output_model=JsonExtractOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ, SkillCapability.SEARCH},
            risk_level="normal"
        ),
        
        synonyms=[
            "query json",
            "extract json path",
            "get json value",
            "提取JSON值",
            "查询JSON",
            "获取JSON字段"
        ],
        examples=[
            {"description": "Extract JSON path", "params": {"relative_path": "data.json", "json_path": "users[0].name"}}
        ],
        permissions=[SkillPermission(name="file_read", description="Read JSON files")],
        tags=["file", "json", "JSON", "提取", "查询"]
    )

    async def run(self, ctx: SkillContext, params: JsonExtractInput) -> JsonExtractOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return JsonExtractOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).", path="", value=None)
        
        if ctx.dry_run:
             return JsonExtractOutput(success=True, message="[dry_run]", path=str(target_path), value=None)

        try:
            if not target_path.exists():
                return JsonExtractOutput(success=False, message="File not found", path=str(target_path), value=None)
            
            text = target_path.read_text(encoding="utf-8")
            obj = json.loads(text)
            val = _get_by_path(obj, params.json_path)
            return JsonExtractOutput(success=True, message="Extracted", path=str(target_path), value=val)
        except Exception as e:
            return JsonExtractOutput(success=False, message=str(e), path=str(target_path), value=None)
