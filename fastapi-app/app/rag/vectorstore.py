"""向量存储：pgvector 主路径，连不上时走本地向量表 + numpy 余弦检索。

对外统一三个动作：add / search / delete_doc，返回的 Hit 一律带相似度得分，
便于前端把“这条知识靠不靠谱”展示给用户。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import numpy as np

from app.config.runtime import runtime
from app.db.gis_store import gis
from app.llm.provider import embedding_model

log = logging.getLogger(__name__)

COLLECTION = "knowledge"


class VectorUnavailable(RuntimeError):
    pass


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class LocalVectorStore:
    name = "local-vector"

    def __init__(self, embeddings) -> None:
        self._embed = embeddings
        self._cache: tuple[np.ndarray, list[dict[str, Any]]] | None = None

    async def add(self, *, doc_id: int, doc_name: str, texts: list[str]) -> int:
        if not texts:
            return 0
        vectors = await self._embed.aembed_documents(texts)
        rows = [
            {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "chunk_index": index,
                "content": text,
                "embedding": json.dumps(vector),
                "metadata": json.dumps({"doc_id": doc_id, "doc_name": doc_name, "source": "local"}),
            }
            for index, (text, vector) in enumerate(zip(texts, vectors))
        ]
        await gis.add_chunks(rows)
        self._cache = None
        return len(rows)

    async def _matrix(self) -> tuple[np.ndarray, list[dict[str, Any]]]:
        if self._cache is not None:
            return self._cache
        chunks = await gis.all_chunks()
        if not chunks:
            self._cache = (np.zeros((0, 0), dtype="float32"), [])
            return self._cache
        matrix = _normalize(np.asarray([c["embedding"] for c in chunks], dtype="float32"))
        meta = [{k: c[k] for k in ("doc_id", "doc_name", "chunk_index", "content")} for c in chunks]
        self._cache = (matrix, meta)
        return self._cache

    async def search(self, query: str, k: int | None = None) -> list[dict[str, Any]]:
        top_k = k or runtime.get_int("rag.top_k", 4)
        matrix, meta = await self._matrix()
        if matrix.size == 0 or not (query or "").strip():
            return []
        vector = _normalize(np.asarray([await self._embed.aembed_query(query)], dtype="float32"))[0]
        scores = matrix @ vector
        order = np.argsort(-scores)[: max(top_k, 1)]
        return [
            {**meta[int(i)], "score": round(float(scores[int(i)]), 4)}
            for i in order
            if scores[int(i)] > 0
        ]

    async def delete_doc(self, doc_id: int) -> int:
        removed = await gis.delete_doc_chunks(doc_id)
        self._cache = None
        return removed

    async def count(self) -> int:
        return await gis.chunk_count()


class PgVectorStore:
    name = "pgvector"

    def __init__(self, embeddings) -> None:
        from langchain_postgres import PGVector

        self._embed = embeddings
        self._vs = PGVector(
            collection_name=COLLECTION,
            embedding=embeddings,
            connection_string=runtime.postgres_dsn,
            use_jsonb=True,
        )

    async def add(self, *, doc_id: int, doc_name: str, texts: list[str]) -> int:
        if not texts:
            return 0
        metadatas = [{"doc_id": str(doc_id), "doc_name": doc_name, "chunk_index": i} for i in range(len(texts))]
        await asyncio.to_thread(self._vs.add_texts, texts, metadatas=metadatas)
        return len(texts)

    async def search(self, query: str, k: int | None = None) -> list[dict[str, Any]]:
        top_k = k or runtime.get_int("rag.top_k", 4)
        if not (query or "").strip():
            return []
        pairs = await asyncio.to_thread(self._vs.similarity_search_with_relevance_scores, query, top_k)
        out = []
        for doc, score in pairs:
            meta = doc.metadata or {}
            out.append(
                {
                    "content": doc.page_content,
                    "score": round(float(score), 4),
                    "doc_id": int(meta.get("doc_id") or 0),
                    "doc_name": meta.get("doc_name", ""),
                    "chunk_index": meta.get("chunk_index", 0),
                }
            )
        return out

    async def delete_doc(self, doc_id: int) -> int:
        try:  # 通过 cmetadata->>'doc_id' 精确清理，不留孤儿向量
            await asyncio.to_thread(self._vs.delete, filter={"doc_id": str(doc_id)})
        except Exception as exc:
            log.debug("PGVector.delete(filter) 不可用，改用 SQL 清理：%s", exc)
            return await gis.delete_doc_chunks(doc_id)
        return 0

    async def count(self) -> int:
        return await gis.chunk_count()


_backend: Any = None
_backend_key: str = ""


def _key() -> str:
    return f"{gis.mode}|{runtime.postgres_dsn}|{runtime.get_str('embed.model')}|{runtime.embed_base_url}"


def vector_store():
    global _backend, _backend_key
    if _backend is not None and _backend_key == _key():
        return _backend
    embeddings = embedding_model()
    if embeddings is None:
        raise VectorUnavailable("未配置嵌入模型，无法使用向量检索；请在「系统配置 → 向量与 RAG」填写后重试")
    _backend = PgVectorStore(embeddings) if gis.mode == "postgis" else LocalVectorStore(embeddings)
    _backend_key = _key()
    return _backend


def reset() -> None:
    global _backend, _backend_key
    _backend = None
    _backend_key = ""


async def on_config_change(changed: set[str]) -> None:
    if any(key.split(".")[0] in {"embed", "llm", "gis"} for key in changed):
        reset()


async def search_knowledge(query: str, k: int | None = None) -> list[dict[str, Any]]:
    """供工作流与 Agent 调用的统一入口：向量库不可用时返回空，由上层跳过知识召回。"""
    try:
        return await vector_store().search(query, k)
    except VectorUnavailable as exc:
        log.info("知识召回跳过：%s", exc)
        return []
    except Exception as exc:
        log.warning("知识检索失败（降级为空结果）：%s", exc)
        return []


async def add_document(doc_id: int, doc_name: str, chunks: list[str]) -> int:
    return await vector_store().add(doc_id=doc_id, doc_name=doc_name, texts=chunks)


async def delete_document(doc_id: int) -> None:
    try:
        await vector_store().delete_doc(doc_id)
    except VectorUnavailable:
        pass


async def chunk_count() -> int:
    try:
        return await vector_store().count()
    except VectorUnavailable:
        return await gis.chunk_count()


async def backend_status() -> dict[str, Any]:
    try:
        store = vector_store()
        return {"backend": store.name, "chunks": await store.count(), "model": runtime.get_str("embed.model"), "ok": True}
    except VectorUnavailable as exc:
        return {"backend": "none", "chunks": 0, "model": runtime.get_str("embed.model"), "ok": False, "message": str(exc)}
    except Exception as exc:
        return {"backend": "error", "chunks": 0, "ok": False, "message": f"{type(exc).__name__}: {str(exc)[:200]}"}
