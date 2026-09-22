"""知识库接口：上传/录入、列表、删除（同步清理向量）、检索测试面板。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config.runtime import runtime
from app.core.deps import get_current_user
from app.models.schemas import KbSearchReq, KbTextReq
from app.models.sys_tables import SysUser
from app.rag import vectorstore
from app.services import knowledge

router = APIRouter(prefix="/api/knowledge", tags=["知识库"])

MAX_UPLOAD = 8 * 1024 * 1024


@router.get("/docs")
async def list_docs(page: int = 1, size: int = 20, keyword: str = "", _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    items, total = await knowledge.list_docs(page=page, size=size, keyword=keyword)
    return {"total": total, "page": page, "size": size, "items": items}


@router.get("/status")
async def kb_status(_: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    backend = await vectorstore.backend_status()
    return {
        **backend,
        "top_k": runtime.get_int("rag.top_k", 4),
        "chunk_size": runtime.get_int("rag.chunk_size", 500),
        "chunk_overlap": runtime.get_int("rag.chunk_overlap", 80),
        "embed_model": runtime.get_str("embed.model"),
        "supported": ["txt", "md", "csv", "json", "pdf"],
    }


@router.post("/text")
async def add_text(req: KbTextReq, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    if not (req.text or "").strip():
        raise HTTPException(status_code=400, detail="文本内容不能为空")
    doc = await knowledge.ingest_text(name=req.name, text=req.text, owner_id=user.id)
    return _doc_response(doc)


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    name: str = Form(default=""),
    user: SysUser = Depends(get_current_user),
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=400, detail="文件超过 8MB 限制")
    try:
        doc = await knowledge.ingest_file(filename=name or file.filename or "未命名文档", data=data, owner_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _doc_response(doc)


@router.delete("/docs/{doc_id}")
async def remove(doc_id: int, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    if not await knowledge.delete_doc(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True, "message": "文档与对应向量已一并删除"}


@router.post("/search")
async def search(req: KbSearchReq, _: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    hits = await knowledge.search_test(req.query, req.k)
    return {
        "query": req.query,
        "count": len(hits),
        "backend": (await vectorstore.backend_status()).get("backend"),
        "items": [
            {
                "doc_id": hit.get("doc_id"),
                "doc_name": hit.get("doc_name"),
                "chunk_index": hit.get("chunk_index"),
                "score": hit.get("score"),
                "text": hit.get("content"),
            }
            for hit in hits
        ],
    }


def _doc_response(doc: dict[str, Any]) -> dict[str, Any]:
    if doc.get("status") == "failed":
        raise HTTPException(status_code=400, detail=doc.get("error") or "文档入库失败")
    return {**doc, "message": f"已切分为 {doc.get('chunk_count')} 片并完成向量化"}
