"""中文友好分块：按中文标点断句，而不是照搬英文的空格/句号切分。"""
from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config.runtime import runtime

SEPARATORS = ["\n\n", "\n", "。", "；", "！", "？", "，", " ", ""]


def split_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    size = chunk_size or runtime.get_int("rag.chunk_size", 500)
    overlap = chunk_overlap or runtime.get_int("rag.chunk_overlap", 80)
    splitter = RecursiveCharacterTextSplitter(
        separators=SEPARATORS,
        chunk_size=max(size, 100),
        chunk_overlap=min(overlap, max(size // 2, 1)),
        length_function=len,
        keep_separator=True,
    )
    return [chunk.strip() for chunk in splitter.split_text(text or "") if chunk.strip()]
