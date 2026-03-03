# app/avatar/skills/builtin/image.py

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional
from pydantic import Field, model_validator
from ..common.path_mixins import PathBindMixin

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext


# ============================================================================
# image.save
# ============================================================================

class ImageSaveInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative image file path (e.g. 'screenshot.png')."
    )
    base64_data: str = Field(..., description="Base64 encoded image data.")
    format: Optional[str] = Field(None, description="Image format: png, jpg, jpeg, webp, gif, bmp. Auto-detected from file extension if not specified.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class ImageSaveOutput(SkillOutput):
    path: str
    size_bytes: int

@register_skill
class ImageSaveSkill(BaseSkill[ImageSaveInput, ImageSaveOutput]):
    spec = SkillSpec(
        name="image.save",
        api_name="image.save",
        aliases=["save_image", "write_image", "image.write"],
        description="Save a Base64 encoded image to a file. Supports PNG, JPG, WebP, GIF, BMP formats. 保存Base64编码的图片到文件。",
        category=SkillCategory.FILE,
        input_model=ImageSaveInput,
        output_model=ImageSaveOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="normal"
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="image:generic",  # 通用图片类型，具体格式从扩展名推断
        artifact_path_field="path",
        
        permissions=[SkillPermission(name="file_write", description="Write image files")],
        synonyms=[
            "save screenshot",
            "save picture",
            "write image",
            "save photo",
            "保存图片",
            "保存截图",
            "保存照片",
            "存储图片",
            "写入图片"
        ],
        examples=[
            {"description": "Save screenshot", "params": {"relative_path": "screenshot.png", "base64_data": "iVBORw0KGgo..."}}
        ],
        tags=["image", "file", "save", "screenshot", "图片", "保存", "截图", "照片"]
    )

    async def run(self, ctx: SkillContext, params: ImageSaveInput) -> ImageSaveOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return ImageSaveOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).", path="", size_bytes=0)

        if ctx.dry_run:
            return ImageSaveOutput(
                success=True,
                message=f"[dry_run] Would save image to: {target_path}",
                path=str(target_path),
                size_bytes=0
            )

        try:
            # Pre-execution validation: Check file extension
            valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
            file_ext = target_path.suffix.lower()
            
            if file_ext not in valid_extensions:
                return ImageSaveOutput(
                    success=False,
                    message=f"Invalid image file extension: {file_ext}. Supported: {', '.join(valid_extensions)}",
                    path=str(target_path),
                    size_bytes=0
                )

            # Decode Base64 data
            try:
                # Remove potential data URI prefix (e.g., "data:image/png;base64,")
                base64_str = params.base64_data
                if ',' in base64_str and base64_str.startswith('data:'):
                    base64_str = base64_str.split(',', 1)[1]
                
                image_bytes = base64.b64decode(base64_str)
            except Exception as e:
                return ImageSaveOutput(
                    success=False,
                    message=f"Failed to decode Base64 data: {str(e)}",
                    path=str(target_path),
                    size_bytes=0
                )

            # Validate decoded data is not empty
            if len(image_bytes) == 0:
                return ImageSaveOutput(
                    success=False,
                    message="Decoded image data is empty",
                    path=str(target_path),
                    size_bytes=0
                )

            # Execute: Write binary data to file
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(image_bytes)

            # Post-execution verification
            if not target_path.exists():
                return ImageSaveOutput(
                    success=False,
                    message=f"Verification Failed: File not found at {target_path} after write",
                    path=str(target_path),
                    size_bytes=0
                )

            # Verify file size
            actual_size = target_path.stat().st_size
            if actual_size != len(image_bytes):
                return ImageSaveOutput(
                    success=False,
                    message=f"Verification Failed: File size mismatch. Expected {len(image_bytes)} bytes, got {actual_size} bytes",
                    path=str(target_path),
                    size_bytes=actual_size
                )

            # Verify file is not empty
            if actual_size == 0:
                return ImageSaveOutput(
                    success=False,
                    message=f"Verification Failed: Saved file is empty",
                    path=str(target_path),
                    size_bytes=0
                )

            return ImageSaveOutput(
                success=True,
                message=f"Image saved successfully: {target_path.name} ({actual_size} bytes, verified)",
                path=str(target_path),
                size_bytes=actual_size
            )

        except PermissionError:
            return ImageSaveOutput(
                success=False,
                message=f"Permission denied: Cannot write to {target_path}",
                path=str(target_path),
                size_bytes=0
            )
        except Exception as e:
            return ImageSaveOutput(
                success=False,
                message=f"Failed to save image: {str(e)}",
                path=str(target_path),
                size_bytes=0
            )


# ============================================================================
# image.read (Future extension - Read image as Base64)
# ============================================================================

class ImageReadInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative image file path."
    )
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

class ImageReadOutput(SkillOutput):
    path: str
    base64_data: str
    size_bytes: int
    format: str

@register_skill
class ImageReadSkill(BaseSkill[ImageReadInput, ImageReadOutput]):
    spec = SkillSpec(
        name="image.read",
        api_name="image.read",
        aliases=["read_image", "load_image"],
        description="Read an image file and return as Base64 encoded data. 读取图片文件并返回Base64编码数据。",
        category=SkillCategory.FILE,
        input_model=ImageReadInput,
        output_model=ImageReadOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal"
        ),
        
        permissions=[SkillPermission(name="file_read", description="Read image files")],
        synonyms=[
            "load image",
            "read picture",
            "get image",
            "读取图片",
            "加载图片",
            "获取图片"
        ],
        examples=[
            {"description": "Read image file", "params": {"relative_path": "photo.jpg"}}
        ],
        tags=["image", "file", "read", "load", "图片", "读取", "加载"]
    )

    async def run(self, ctx: SkillContext, params: ImageReadInput) -> ImageReadOutput:
        # 1. 优先使用 abs_path
        if params.abs_path:
             target_path = Path(params.abs_path)
        # 2. 否则使用 relative_path
        elif params.relative_path:
             target_path = ctx.resolve_path(params.relative_path)
        # 3. 如果都没有，报错
        else:
             return ImageReadOutput(success=False, message="No valid path provided (neither relative_path nor abs_path).", path="", base64_data="", size_bytes=0, format="")

        if ctx.dry_run:
            return ImageReadOutput(
                success=True,
                message=f"[dry_run] Would read image from: {target_path}",
                path=str(target_path),
                base64_data="",
                size_bytes=0,
                format=""
            )

        try:
            # Pre-execution validation
            if not target_path.exists():
                return ImageReadOutput(
                    success=False,
                    message=f"Image file not found: {target_path}",
                    path=str(target_path),
                    base64_data="",
                    size_bytes=0,
                    format=""
                )

            if not target_path.is_file():
                return ImageReadOutput(
                    success=False,
                    message=f"Path is not a file: {target_path}",
                    path=str(target_path),
                    base64_data="",
                    size_bytes=0,
                    format=""
                )

            # Check file extension
            valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
            file_ext = target_path.suffix.lower()
            
            if file_ext not in valid_extensions:
                return ImageReadOutput(
                    success=False,
                    message=f"Invalid image file extension: {file_ext}. Supported: {', '.join(valid_extensions)}",
                    path=str(target_path),
                    base64_data="",
                    size_bytes=0,
                    format=""
                )

            # Execute: Read binary data and encode to Base64
            image_bytes = target_path.read_bytes()
            base64_data = base64.b64encode(image_bytes).decode('utf-8')

            # Post-execution verification
            if len(image_bytes) == 0:
                return ImageReadOutput(
                    success=False,
                    message=f"Verification Failed: Image file is empty",
                    path=str(target_path),
                    base64_data="",
                    size_bytes=0,
                    format=file_ext[1:]
                )

            return ImageReadOutput(
                success=True,
                message=f"Image read successfully: {target_path.name} ({len(image_bytes)} bytes)",
                path=str(target_path),
                base64_data=base64_data,
                size_bytes=len(image_bytes),
                format=file_ext[1:]  # Remove the dot
            )

        except PermissionError:
            return ImageReadOutput(
                success=False,
                message=f"Permission denied: Cannot read {target_path}",
                path=str(target_path),
                base64_data="",
                size_bytes=0,
                format=""
            )
        except Exception as e:
            return ImageReadOutput(
                success=False,
                message=f"Failed to read image: {str(e)}",
                path=str(target_path),
                base64_data="",
                size_bytes=0,
                format=""
            )

