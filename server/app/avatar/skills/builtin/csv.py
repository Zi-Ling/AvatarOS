# app/avatar/skills/builtin/csv.py

from __future__ import annotations

import csv
import logging
from typing import List, Any, Optional
from pydantic import Field, model_validator
from ..common.path_normalizer import normalize_file_extension
from ..common.path_mixins import PathBindMixin

from ..base import BaseSkill, SkillSpec, SkillCategory, SkillPermission, SkillMetadata, SkillDomain, SkillCapability
from ..schema import SkillInput, SkillOutput
from ..registry import register_skill
from ..context import SkillContext

logger = logging.getLogger(__name__)


# ============================================================================
# csv.read
# ============================================================================

class CsvReadInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative CSV path."
    )
    delimiter: str = Field(",", description="Field delimiter.")
    max_rows: int = Field(1000, description="Max rows to read.")
    has_header: bool = Field(True, description="If first row is header.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

    @model_validator(mode="after")
    def normalize_ext(self):
        if self.relative_path:
            self.relative_path = normalize_file_extension(
                self.relative_path, 
                default_ext=".csv", 
                allowed_exts={".csv", ".tsv"}
            )
        return self

class CsvReadOutput(SkillOutput):
    path: str
    header: Optional[List[Any]] = None
    rows: List[List[Any]] = []
    rows_count: int = 0

@register_skill
class CsvReadSkill(BaseSkill[CsvReadInput, CsvReadOutput]):
    spec = SkillSpec(
        name="csv.read",
        api_name="csv.read",
        aliases=["csv.load", "read_csv"],
        description="Read CSV file. 读取CSV文件数据。",
        category=SkillCategory.FILE,
        input_model=CsvReadInput,
        output_model=CsvReadOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.READ},
            risk_level="normal",
            file_extensions=[".csv", ".tsv"]
        ),
        
        synonyms=[
            "read csv file",
            "load csv data",
            "parse csv",
            "读取CSV",
            "加载CSV数据",
            "解析CSV"
        ],
        examples=[
            {"description": "Read CSV file with default settings", "params": {"relative_path": "data.csv"}},
            {"description": "Read CSV with custom delimiter", "params": {"relative_path": "data.tsv", "delimiter": "\t"}}
        ],
        permissions=[SkillPermission(name="file_read", description="Read CSV")],
        tags=["file", "csv", "数据", "读取", "CSV"]
    )

    async def run(self, ctx: SkillContext, params: CsvReadInput) -> CsvReadOutput:
        target_path = ctx.resolve_path(params.relative_path)

        if ctx.dry_run:
             return CsvReadOutput(success=True, message="[dry_run]", path=str(target_path))

        try:
            if not target_path.exists():
                 return CsvReadOutput(success=False, message="File not found", path=str(target_path))
            
            rows = []
            header = None
            
            with target_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f, delimiter=params.delimiter)
                for idx, row in enumerate(reader):
                    if idx == 0 and params.has_header:
                        header = row
                        continue
                    rows.append(row)
                    if len(rows) >= params.max_rows:
                        break
            
            return CsvReadOutput(
                success=True, message="Read CSV",
                path=str(target_path),
                header=header,
                rows=rows,
                rows_count=len(rows)
            )
        except Exception as e:
             return CsvReadOutput(success=False, message=str(e), path=str(target_path))


# ============================================================================
# csv.write
# ============================================================================

class CsvWriteInput(PathBindMixin, SkillInput):
    # relative_path 可以允许为空，因为有可能完全靠 file_path/abs_path 驱动
    relative_path: str | None = Field(
        None, description="Relative CSV path."
    )
    rows: List[List[Any]] = Field(..., description="List of rows.")
    delimiter: str = Field(",", description="Field delimiter.")
    
    # 可选：增加一个 abs_path，直接使用绝对路径时用
    abs_path: str | None = Field(
        None, description="Absolute file path. If provided, takes precedence."
    )

    @model_validator(mode="before")
    def handle_dict_inputs(cls, values):
        """
        鲁棒性处理：自动从字典中提取 rows 数据
        """
        if not isinstance(values, dict):
            return values

        if "rows" in values and isinstance(values["rows"], dict):
            incoming_dict = values["rows"]
            
            # 策略 1: 检查是否有 'rows' 字段 (针对 csv.read / excel.read)
            if "rows" in incoming_dict and isinstance(incoming_dict["rows"], list):
                 logger.debug(f"CsvSkill: Auto-extracted 'rows' from dict input")
                 values["rows"] = incoming_dict["rows"]
                 return values
            
            # 策略 2: 检查是否有 'data' 字段
            if "data" in incoming_dict and isinstance(incoming_dict["data"], list):
                 logger.debug(f"CsvSkill: Auto-extracted 'data' from dict input as rows")
                 values["rows"] = incoming_dict["data"]
                 return values

            logger.debug(f"CsvSkill: Warning - received dict for rows, but no extractable data found. {incoming_dict.keys()}")
            
        return values

    @model_validator(mode="after")
    def normalize_ext(self):
        if self.relative_path:
            self.relative_path = normalize_file_extension(
                self.relative_path, 
                default_ext=".csv", 
                allowed_exts={".csv", ".tsv"}
            )
        return self

class CsvWriteOutput(SkillOutput):
    path: str
    rows_count: int

@register_skill
class CsvWriteSkill(BaseSkill[CsvWriteInput, CsvWriteOutput]):
    spec = SkillSpec(
        name="csv.write",
        api_name="csv.write",
        aliases=["csv.save", "write_csv"],
        description="Write rows to CSV (overwrite). 写入数据到CSV文件。",
        category=SkillCategory.FILE,
        input_model=CsvWriteInput,
        output_model=CsvWriteOutput,
        
        # Capability Routing Metadata (Gatekeeper V2)
        meta=SkillMetadata(
            domain=SkillDomain.FILE,
            capabilities={SkillCapability.WRITE, SkillCapability.CREATE},
            risk_level="high",
            file_extensions=[".csv", ".tsv"]
        ),
        
        # ✅ Artifact Management（混合方案：声明式）
        produces_artifact=True,
        artifact_type="file:csv",
        artifact_path_field="path",
        
        synonyms=[
            "write csv file",
            "save csv data",
            "export csv",
            "写入CSV",
            "保存CSV数据",
            "导出CSV"
        ],
        examples=[
            {"description": "Write data to CSV", "params": {"relative_path": "output.csv", "rows": [["Name", "Age"], ["Alice", "30"]]}}
        ],
        permissions=[SkillPermission(name="file_write", description="Write CSV")],
        tags=["file", "csv", "数据", "保存", "写入", "CSV"]
    )

    async def run(self, ctx: SkillContext, params: CsvWriteInput) -> CsvWriteOutput:
        target_path = ctx.resolve_path(params.relative_path)

        if ctx.dry_run:
             return CsvWriteOutput(success=True, message="[dry_run]", path=str(target_path), rows_count=len(params.rows))

        try:
            # Pre-execution validation
            if not params.rows:
                return CsvWriteOutput(success=False, message="No rows to write", path=str(target_path), rows_count=0)
            
            # Execute
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with target_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=params.delimiter)
                writer.writerows(params.rows)
            
            # Post-execution verification
            if not target_path.exists():
                return CsvWriteOutput(success=False, message="Verification Failed: File not found after write", path=str(target_path), rows_count=0)
            
            # Verify file content by reading it back
            try:
                with target_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f, delimiter=params.delimiter)
                    written_rows = list(reader)
                    
                    if len(written_rows) != len(params.rows):
                        return CsvWriteOutput(
                            success=False,
                            message=f"Verification Failed: Expected {len(params.rows)} rows, but file has {len(written_rows)} rows",
                            path=str(target_path),
                            rows_count=len(written_rows)
                        )
            except Exception as e:
                return CsvWriteOutput(success=False, message=f"Verification Failed: Cannot read back CSV: {e}", path=str(target_path), rows_count=0)
            
            return CsvWriteOutput(success=True, message=f"Written CSV to {target_path.name} ({len(params.rows)} rows, verified)", path=str(target_path), rows_count=len(params.rows))
        except PermissionError:
            return CsvWriteOutput(success=False, message=f"Permission denied: Cannot write to {target_path}", path=str(target_path), rows_count=0)
        except Exception as e:
             return CsvWriteOutput(success=False, message=str(e), path=str(target_path), rows_count=0)
