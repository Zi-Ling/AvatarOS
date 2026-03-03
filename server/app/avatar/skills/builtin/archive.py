# app/avatar/skills/builtin/archive.py

from __future__ import annotations

import os
import json
import logging
import zipfile
from pathlib import Path
from typing import List, Optional
from pydantic import Field, model_validator

logger = logging.getLogger(__name__)

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# archive.zip
# ============================================================================

class ArchiveZipInput(SkillInput):
    relative_paths_json: str = Field(..., description="JSON array of relative paths to include.")
    output_relative_path: str = Field(..., description="Relative output zip path.")

class ArchiveZipOutput(SkillOutput):
    output_path: str
    inputs: List[str]

@register_skill
class ArchiveZipSkill(BaseSkill[ArchiveZipInput, ArchiveZipOutput]):
    spec = SkillSpec(
        name="archive.zip",
        api_name="archive.zip",
        aliases=["zip", "compress", "file.zip"],
        description="Create a zip archive from multiple paths. 创建ZIP压缩文件。",
        category=SkillCategory.FILE,
        input_model=ArchiveZipInput,
        output_model=ArchiveZipOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.CREATE, SkillCapability.WRITE},
            risk_level="normal"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="archive:zip",
        artifact_path_field="output_path",  # 注意：archive.zip 使用 output_path 而不是 path
        artifact_metadata={"contains_multiple": True},  # 额外元数据：表示包含多个文件
        
        permissions=[SkillPermission(name="file_write", description="Create zip archives")],
        tags=["archive", "zip", "压缩", "ZIP", "打包"]
    )

    async def run(self, ctx: SkillContext, params: ArchiveZipInput) -> ArchiveZipOutput:
        try:
            rel_paths = json.loads(params.relative_paths_json)
            if not isinstance(rel_paths, list): raise ValueError("Must be JSON array")
        except Exception as e:
            return ArchiveZipOutput(success=False, message=str(e), output_path="", inputs=[])

        output_path = ctx.resolve_path(params.output_relative_path)

        if ctx.dry_run:
            return ArchiveZipOutput(
                success=True, 
                message=f"[dry_run] Zip {output_path}", 
                output_path=str(output_path), 
                inputs=rel_paths
            )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for rel in rel_paths:
                    p = ctx.resolve_path(rel)
                    if not p.exists():
                        return ArchiveZipOutput(success=False, message=f"Not found: {p}", output_path="", inputs=[])
                    
                    if p.is_dir():
                        for sub in p.rglob("*"):
                            if sub.is_file():
                                arcname = sub.relative_to(ctx.base_path) if ctx.base_path else sub.name
                                zf.write(sub, arcname=str(arcname))
                    else:
                        arcname = p.relative_to(ctx.base_path) if ctx.base_path else p.name
                        zf.write(p, arcname=str(arcname))
            
            return ArchiveZipOutput(
                success=True,
                message=f"Zip created: {output_path}",
                output_path=str(output_path),
                inputs=rel_paths,
                # FS Metadata
                fs_operation='created',
                fs_path=params.output_relative_path,
                fs_type='file'
            )
        except Exception as e:
            return ArchiveZipOutput(success=False, message=str(e), output_path=str(output_path), inputs=rel_paths)


# ============================================================================
# archive.unzip
# ============================================================================

class ArchiveUnzipInput(SkillInput):
    zip_relative_path: str | None = Field(None, description="Relative zip file path.")
    output_relative_dir: str = Field(..., description="Relative output directory.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute zip file path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def bind_paths(cls, values):
        """
        处理几种情况：
        1. Orchestrator 直接传了 file_path → 绑定到 zip_relative_path / abs_path
        2. zip_relative_path 是一个 dict（上游 _raw_result 被塞进来了）
        """
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            # 绝对路径：放到 abs_path，同时给 zip_relative_path 一个 basename 方便日志/UI 展示
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("zip_relative_path", os.path.basename(file_path))
            else:
                # 已经是相对路径，就直接写到 zip_relative_path
                values.setdefault("zip_relative_path", file_path)
            logger.debug(f"ArchiveUnzipSkill: bound from file_path={file_path}")
            return values

        # ⭐⭐ 情况 2：zip_relative_path 本身是一个 dict
        if "zip_relative_path" in values and isinstance(values["zip_relative_path"], dict):
            incoming_dict = values["zip_relative_path"]
            
            # 尝试从几个常见 key 中提取路径
            for key in ("path", "file_path", "fs_path"):
                v = incoming_dict.get(key)
                if isinstance(v, str):
                    if os.path.isabs(v):
                        values["abs_path"] = v
                        values["zip_relative_path"] = os.path.basename(v)
                    else:
                        values["zip_relative_path"] = v
                    logger.debug(f"ArchiveUnzipSkill: Auto-extracted '{key}' from dict as path → {v}")
                    return values
            
            logger.warning(
                "ArchiveUnzipSkill: received dict for zip_relative_path, "
                f"but no extractable path found. keys={list(incoming_dict.keys())}"
            )
            
        return values

class ArchiveUnzipOutput(SkillOutput):
    zip_path: str
    output_dir: str

@register_skill
class ArchiveUnzipSkill(BaseSkill[ArchiveUnzipInput, ArchiveUnzipOutput]):
    spec = SkillSpec(
        name="archive.unzip",
        api_name="archive.unzip",
        aliases=["unzip", "extract", "file.unzip"],
        description="Extract a zip archive.",
        category=SkillCategory.FILE,
        input_model=ArchiveUnzipInput,
        output_model=ArchiveUnzipOutput,
        
        # Capability Routing
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.CREATE, SkillCapability.WRITE, SkillCapability.MODIFY},
            risk_level="normal"
        ),
        
        permissions=[SkillPermission(name="file_write", description="Extract files")],
        tags=["archive", "unzip"]
    )

    async def run(self, ctx: SkillContext, params: ArchiveUnzipInput) -> ArchiveUnzipOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             zip_path = Path(params.abs_path)
        # 2. 否则使用 zip_relative_path
        elif params.zip_relative_path:
             zip_path = ctx.resolve_path(params.zip_relative_path)
        # 3. 如果都没有，报错
        else:
             return ArchiveUnzipOutput(success=False, message="No valid zip path provided (neither zip_relative_path nor abs_path).", zip_path="", output_dir="")

        output_dir = ctx.resolve_path(params.output_relative_dir)

        if ctx.dry_run:
            return ArchiveUnzipOutput(
                success=True, 
                message=f"[dry_run] Unzip {zip_path} -> {output_dir}", 
                zip_path=str(zip_path), 
                output_dir=str(output_dir)
            )

        try:
            if not zip_path.exists():
                return ArchiveUnzipOutput(success=False, message=f"Not found: {zip_path}", zip_path=str(zip_path), output_dir="")
            
            output_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(output_dir)
            
            return ArchiveUnzipOutput(
                success=True, 
                message=f"Extracted to {output_dir}", 
                zip_path=str(zip_path), 
                output_dir=str(output_dir),
                # FS Metadata - Directory modified/created
                fs_operation='modified',
                fs_path=params.output_relative_dir,
                fs_type='dir'
            )
        except Exception as e:
            return ArchiveUnzipOutput(success=False, message=str(e), zip_path=str(zip_path), output_dir=str(output_dir))
