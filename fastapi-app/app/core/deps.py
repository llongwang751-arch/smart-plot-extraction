"""依赖注入：登录凭证解析与角色校验。"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Header, HTTPException, Query

from app.core.security import decode_token
from app.models.sys_tables import SysUser


async def get_current_user(
    authorization: str = Header(default=""),
    token: str = Query(default=""),
) -> SysUser:
    raw = authorization[7:] if authorization.lower().startswith("bearer ") else (authorization or token)
    payload = decode_token(raw.strip())
    if not payload:
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录")
    user = await SysUser.get_or_none(id=int(payload.get("uid") or 0))
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在或已被删除")
    if not user.enabled:
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    return user


async def require_admin(user: SysUser = Depends(get_current_user)) -> SysUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="该操作仅管理员可用")
    return user


def assert_self_or_admin(target_id: int, user: SysUser) -> None:
    """防止改一下请求里的 id 就能操作他人账号。"""
    if user.role != "admin" and int(target_id) != int(user.id):
        raise HTTPException(status_code=403, detail="只能操作本人账号，或使用管理员身份")


def user_out(user: SysUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.nickname or user.username,
        "email": user.email or "",
        "phone": user.phone or "",
        "role": user.role,
        "is_admin": user.role == "admin",
        "enabled": bool(user.enabled),
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else "",
        "last_login_at": user.last_login_at.strftime("%Y-%m-%d %H:%M:%S") if user.last_login_at else "",
    }
