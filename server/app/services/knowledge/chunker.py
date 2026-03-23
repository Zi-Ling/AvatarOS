# app/services/knowledge/chunker.py
"""文档分块器 — 固定窗口 + 段落两种策略"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    """分块配置"""
    strategy: str = "fixed_window"  # fixed_window / paragraph
    window_size: int = 512          # 字符数（近似 token）
    overlap: int = 64               # 重叠字符数


@dataclass
class ChunkMeta:
    """单个 chunk 的元数据"""
    chunk_index: int
    start_offset: int
    end_offset: int
    text: str
    chunk_id: str = ""  # 由 make_chunk_id 统一生成


class Chunker:
    """文档分块器"""

    def __init__(self, config: ChunkConfig | None = None):
        self.config = config or ChunkConfig()

    @staticmethod
    def make_chunk_id(document_id: str, chunk_index: int) -> str:
        """统一生成 chunk_id，避免多处拼接不一致。"""
        return f"{document_id}__chunk_{chunk_index:04d}"

    def chunk(self, text: str, document_id: str) -> list[ChunkMeta]:
        """根据策略分块，返回 ChunkMeta 列表。"""
        if not text:
            return []

        if self.config.strategy == "paragraph":
            chunks = self._paragraph_chunk(text)
        else:
            chunks = self._fixed_window_chunk(text)

        # 填充 chunk_id
        for c in chunks:
            c.chunk_id = self.make_chunk_id(document_id, c.chunk_index)
        return chunks

    def _fixed_window_chunk(self, text: str) -> list[ChunkMeta]:
        """
        固定窗口 + 重叠分块。
        最后一个 chunk 允许短于 window_size，独立保留。
        """
        ws = self.config.window_size
        ov = self.config.overlap
        step = ws - ov
        if step <= 0:
            step = max(ws, 1)

        chunks: list[ChunkMeta] = []
        offset = 0
        idx = 0
        while offset < len(text):
            end = min(offset + ws, len(text))
            chunks.append(ChunkMeta(
                chunk_index=idx,
                start_offset=offset,
                end_offset=end,
                text=text[offset:end],
            ))
            idx += 1
            # 如果本 chunk 已经覆盖到文末，结束
            if end >= len(text):
                break
            offset = offset + step
        return chunks

    def _paragraph_chunk(self, text: str) -> list[ChunkMeta]:
        """按段落边界（\\n\\n）分块。"""
        paragraphs = text.split("\n\n")
        chunks: list[ChunkMeta] = []
        offset = 0
        idx = 0
        for para in paragraphs:
            if not para:
                offset += 2  # skip the \n\n
                continue
            start = text.index(para, offset)
            end = start + len(para)
            chunks.append(ChunkMeta(
                chunk_index=idx,
                start_offset=start,
                end_offset=end,
                text=para,
            ))
            idx += 1
            offset = end
        return chunks
