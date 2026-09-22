"""知识库服务：文档入库（切块 → 向量化）、检索测试、删除时同步清理向量。"""
from __future__ import annotations

import logging
from typing import Any

from app.config.runtime import runtime
from app.models.sys_tables import KbDocument
from app.rag.loaders import read_document
from app.rag.splitter import split_text
from app.rag.vectorstore import VectorUnavailable, add_document, delete_document, search_knowledge

log = logging.getLogger(__name__)


async def ingest_text(*, name: str, text: str, owner_id: int = 0, source: str = "text") -> dict[str, Any]:
    chunks = split_text(text or "")
    doc = await KbDocument.create(
        name=name[:256] or "未命名文本",
        source=source,
        file_ext="md" if source == "text" else "",
        size_bytes=len((text or "").encode("utf-8")),
        char_count=len(text or ""),
        chunk_count=len(chunks),
        status="pending",
        owner_id=owner_id,
    )
    if not chunks:
        doc.status = "failed"
        doc.error = "文档内容为空或无法切分"
        await doc.save()
        return _as_dict(doc)
    try:
        await add_document(doc.id, doc.name, chunks)
        doc.status = "ready"
    except VectorUnavailable as exc:
        doc.status = "failed"
        doc.error = str(exc)
    except Exception as exc:
        log.exception("向量化失败")
        doc.status = "failed"
        doc.error = f"{type(exc).__name__}: {str(exc)[:200]}"
    await doc.save()
    return _as_dict(doc, chunks=len(chunks))


async def ingest_file(*, filename: str, data: bytes, owner_id: int = 0) -> dict[str, Any]:
    text, note = read_document(filename, data)
    return await ingest_text(name=filename, text=text, owner_id=owner_id, source="upload")


async def list_docs(page: int = 1, size: int = 20, keyword: str = "") -> tuple[list[dict[str, Any]], int]:
    query = KbDocument.all()
    if keyword:
        query = query.filter(name__contains=keyword)
    total = await query.count()
    rows = await query.order_by("-created_at").limit(size).offset((max(page, 1) - 1) * size)
    return [_as_dict(row) for row in rows], total


async def get_doc(doc_id: int) -> KbDocument | None:
    return await KbDocument.get_or_none(id=doc_id)


async def delete_doc(doc_id: int) -> bool:
    doc = await get_doc(doc_id)
    if not doc:
        return False
    await delete_document(doc_id)  # 同步清理向量，不留脏数据
    await doc.delete()
    return True


async def search_test(query: str, k: int | None = None) -> list[dict[str, Any]]:
    return await search_knowledge(query, k or runtime.get_int("rag.top_k", 4))


def _as_dict(doc: KbDocument, **extra: Any) -> dict[str, Any]:
    payload = {
        "id": doc.id,
        "name": doc.name,
        "source": doc.source,
        "file_ext": doc.file_ext,
        "size_bytes": doc.size_bytes,
        "char_count": doc.char_count,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "error": doc.error,
        "created_at": doc.created_at.strftime("%Y-%m-%d %H:%M:%S") if doc.created_at else "",
    }
    payload.update(extra)
    return payload
