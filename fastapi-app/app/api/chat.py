"""智能问答接口：ReAct Agent + 会话持久化，检索来源与工具轨迹一并返回。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config.runtime import runtime
from app.core.deps import get_current_user
from app.models.schemas import ChatReq, SessionTitleReq
from app.models.sys_tables import ChatMessage, ChatSession, SysUser
from app.workflows.agent import ask_agent

router = APIRouter(prefix="/api/chat", tags=["智能问答"])


@router.get("/sessions")
async def list_sessions(user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    rows = await ChatSession.filter(user_id=user.id).order_by("-updated_at").limit(50)
    return {
        "items": [
            {
                "id": row.id,
                "title": row.title,
                "updated_at": row.updated_at.strftime("%Y-%m-%d %H:%M:%S") if row.updated_at else "",
                "messages": await ChatMessage.filter(session_id=row.id).count(),
            }
            for row in rows
        ]
    }


@router.post("/sessions")
async def create_session(user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    row = await ChatSession.create(user_id=user.id, title="新会话")
    return {"id": row.id, "title": row.title}


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: int, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    await _owned(session_id, user)
    rows = await ChatMessage.filter(session_id=session_id).order_by("id").limit(200)
    return {
        "items": [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "sources": _load(row.sources),
                "calls": _load(row.tool_trace),
                "geojson": _load(row.geojson) if row.geojson else None,
                "elapsed_ms": row.elapsed_ms,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else "",
            }
            for row in rows
        ]
    }


@router.put("/sessions/{session_id}")
async def rename_session(session_id: int, req: SessionTitleReq, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    row = await _owned(session_id, user)
    row.title = (req.title or "新会话")[:60]
    await row.save()
    return {"id": row.id, "title": row.title}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    await _owned(session_id, user)
    await ChatMessage.filter(session_id=session_id).delete()
    await ChatSession.filter(id=session_id).delete()
    return {"ok": True, "message": "会话已删除"}


@router.post("/ask")
async def ask(req: ChatReq, user: SysUser = Depends(get_current_user)) -> dict[str, Any]:
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入问题")

    session = await ChatSession.get_or_none(id=req.session_id, user_id=user.id) if req.session_id else None
    if session is None:
        session = await ChatSession.create(user_id=user.id, title=message[:24] or "新会话")
    history = await ChatMessage.filter(session_id=session.id).order_by("-id").limit(8)
    payload = [{"role": row.role, "content": row.content} for row in reversed(history)]

    user_row = await ChatMessage.create(session_id=session.id, role="user", content=message)
    result = await ask_agent(message, payload)

    assistant = await ChatMessage.create(
        session_id=session.id,
        role="assistant",
        content=result.get("answer", ""),
        sources=json.dumps(result.get("sources") or [], ensure_ascii=False),
        tool_trace=json.dumps(result.get("calls") or [], ensure_ascii=False),
        geojson=json.dumps(result.get("plots"), ensure_ascii=False) if result.get("plots") else "",
        elapsed_ms=int(result.get("elapsed_ms") or 0),
    )
    session.updated_at = assistant.created_at
    if session.title in {"新会话", ""}:
        session.title = message[:24]
    await session.save()

    return {
        "answer": result.get("answer", ""),
        "sources": result.get("sources") or [],
        "plots": result.get("plots"),
        "calls": result.get("calls") or [],
        "via": result.get("via", ""),
        "steps": result.get("steps", 0),
        "max_steps": runtime.get_int("llm.max_steps", 8),
        "elapsed_ms": result.get("elapsed_ms", 0),
        "session_id": session.id,
        "message_id": assistant.id,
        "user_message_id": user_row.id,
    }


async def _owned(session_id: int, user: SysUser) -> ChatSession:
    row = await ChatSession.get_or_none(id=session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if user.role != "admin" and row.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    return row


def _load(raw: Any) -> Any:
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (ValueError, TypeError):
        return []
