import os
import logging
from pydantic import model_validator

logger = logging.getLogger(__name__)

class SourceTargetAliasMixin:
    """
    Mixin for normalizing source/destination parameter aliases.
    
    Helps robustly handle LLM hallucinations like "source_path", "dest_dir", etc.
    Expects the consuming model to define:
    - src: str | None
    - dst: str | None
    """

    @model_validator(mode="before")
    def normalize_aliases(cls, values):
        if not isinstance(values, dict):
            return values

        # Define common aliases (centralized management)
        # Priority: Canonical Name > Alias 1 > Alias 2 ...
        alias_map = {
            "src": [
                "source", "source_path", "src_path", 
                "from", "from_path", "origin", "input_path", "input_file"
            ],
            "dst": [
                "dest", "destination", "destination_path", "dst_path",
                "target", "target_path", "to", "to_path", "output_path", "output_file"
            ]
        }
        
        for canonical, aliases in alias_map.items():
            # If canonical key exists and has value, skip
            if values.get(canonical):
                continue
                
            # Try finding value in aliases
            for alias in aliases:
                if values.get(alias):
                    val = values[alias]
                    values[canonical] = val
                    logger.debug(f"{cls.__name__}: Normalized alias '{alias}' -> '{canonical}'")
                    break
        
        return values

class PathBindMixin:
    """
    Mixin for binding file paths from orchestrator outputs or dict inputs.
    
    Expects the consuming model to define:
    - relative_path: str | None
    - abs_path: str | None (optional but recommended)
    """

    @model_validator(mode="before")
    def bind_paths(cls, values):
        """
        处理几种情况：
        1. Orchestrator 直接传了 file_path → 最高优先级
        2. relative_path 是一个 dict（上游 _raw_result 被塞进来了）
        3. 其他情况保持原样
        """
        if not isinstance(values, dict):
            return values

        # ⭐⭐ 情况 1：Orchestrator 传了 file_path（最推荐的方式）
        file_path = values.get("file_path")
        if isinstance(file_path, str):
            # 绝对路径：放到 abs_path，同时给 relative_path 一个 basename 方便日志/UI 展示
            if os.path.isabs(file_path):
                values.setdefault("abs_path", file_path)
                values.setdefault("relative_path", os.path.basename(file_path))
            else:
                # 已经是相对路径，就直接写到 relative_path
                values.setdefault("relative_path", file_path)
            logger.debug(f"{cls.__name__}: bound from file_path={file_path}")
            return values

        # ⭐⭐ 情况 1.5：filename 字段（word.write 等技能常用）
        filename = values.get("filename")
        if isinstance(filename, str) and not values.get("relative_path"):
            if os.path.isabs(filename):
                values.setdefault("abs_path", filename)
                values.setdefault("relative_path", os.path.basename(filename))
            else:
                values.setdefault("relative_path", filename)
            logger.debug(f"{cls.__name__}: bound from filename={filename}")
            return values

        # ⭐⭐ 情况 2：relative_path 本身是一个 dict（LLM 把整个输出塞进来了）
        if "relative_path" in values and isinstance(values["relative_path"], dict):
            incoming_dict = values["relative_path"]
            
            # 尝试从几个常见 key 中提取路径
            for key in ("path", "file_path", "fs_path"):
                v = incoming_dict.get(key)
                if isinstance(v, str):
                    if os.path.isabs(v):
                        values["abs_path"] = v
                        values["relative_path"] = os.path.basename(v)
                    else:
                        values["relative_path"] = v
                    logger.debug(f"{cls.__name__}: Auto-extracted '{key}' from dict as path → {v}")
                    return values
                    
            logger.warning(
                f"{cls.__name__}: received dict for relative_path, "
                f"but no extractable path found. keys={list(incoming_dict.keys())}"
            )
            
        return values
    
    @model_validator(mode="after")
    def ensure_path_exists(self):
        """
        写操作必须保证有明确的文件路径。
        如果 relative_path 和 abs_path 都为 None，自动生成默认文件名。
        """
        if not self.relative_path and not getattr(self, 'abs_path', None):
            # 根据类名推断默认文件名
            skill_type = self.__class__.__name__.lower()
            if 'excel' in skill_type or 'xlsx' in skill_type:
                default_name = "output.xlsx"
            elif 'word' in skill_type or 'docx' in skill_type:
                default_name = "output.docx"
            elif 'csv' in skill_type:
                default_name = "output.csv"
            else:
                default_name = "output.txt"
            
            self.relative_path = default_name
            logger.warning(f"{self.__class__.__name__}: No path provided, using default: {default_name}")
        
        return self
