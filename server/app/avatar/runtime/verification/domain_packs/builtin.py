"""
Built-in DomainPacks for common execution scenarios.
"""
from __future__ import annotations

from app.avatar.runtime.verification.domain_packs.domain_pack import DomainPack

# ---------------------------------------------------------------------------
# file_batch_processing
# ---------------------------------------------------------------------------
FILE_BATCH_PROCESSING = DomainPack(
    pack_id="file_batch_processing",
    name="批量文件处理",
    description="适用于批量读取、转换、写入文件的场景",
    prompt_hint=(
        "当前场景：批量文件处理。\n"
        "请确保每个文件操作步骤都有明确的输入路径和输出路径，"
        "并在完成后验证输出文件存在且格式正确。"
    ),
    verifier_pack={},
    artifact_types=["file", "report"],
    supported_goal_types=[
        "batch*file*", "process*file*", "convert*file*",
        "批量*文件*", "处理*文件*", "转换*文件*",
    ],
)

# ---------------------------------------------------------------------------
# report_generation
# ---------------------------------------------------------------------------
REPORT_GENERATION = DomainPack(
    pack_id="report_generation",
    name="报告生成",
    description="适用于生成分析报告、摘要文档的场景",
    prompt_hint=(
        "当前场景：报告生成。\n"
        "请确保报告包含完整的标题、摘要、正文和结论部分，"
        "输出格式为 Markdown 或 PDF，并验证报告内容完整性。"
    ),
    verifier_pack={},
    artifact_types=["report", "file"],
    supported_goal_types=[
        "generate*report*", "create*report*", "write*report*",
        "生成*报告*", "创建*报告*", "撰写*报告*",
    ],
)

# ---------------------------------------------------------------------------
# repo_analysis
# ---------------------------------------------------------------------------
REPO_ANALYSIS = DomainPack(
    pack_id="repo_analysis",
    name="代码仓库分析",
    description="适用于代码仓库扫描、依赖分析、质量检查的场景",
    prompt_hint=(
        "当前场景：代码仓库分析。\n"
        "请先列出仓库结构，再逐步分析各模块依赖关系和代码质量，"
        "最终输出结构化的分析报告。"
    ),
    verifier_pack={},
    artifact_types=["report", "table"],
    supported_goal_types=[
        "analyze*repo*", "scan*code*", "audit*code*",
        "分析*仓库*", "扫描*代码*", "审计*代码*",
    ],
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
BUILTIN_DOMAIN_PACKS: dict[str, DomainPack] = {
    FILE_BATCH_PROCESSING.pack_id: FILE_BATCH_PROCESSING,
    REPORT_GENERATION.pack_id: REPORT_GENERATION,
    REPO_ANALYSIS.pack_id: REPO_ANALYSIS,
}
