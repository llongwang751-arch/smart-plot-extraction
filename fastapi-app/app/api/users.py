"""用户管理（仅管理员）：管理员接口在后端强制校验身份，而不是只藏菜单。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import require_admin, user_out
from app.core.security import hash_password
from app.models.schemas import UserAdminReq
from app.models.sys_tables import ChatSession, SysUser

router = APIRouter(prefix="/api/users", tags=["用户管理"], dependencies=[Depends(require_admin)])


@router.get("")
async def list_users(keyword: str = "", page: int = 1, size: int = 20) -> dict:
    query = SysUser.all()
    if keyword:
        query = query.filter(username__contains=keyword)
    total = await query.count()
    rows = await query.order_by("id").limit(size).offset((max(page, 1) - 1) * size)
    return {"total": total, "items": [user_out(row) for row in rows]}


@router.post("")
async def create_user(req: UserAdminReq) -> dict:
    username = (req.username or "").strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="用户名与初始密码不能为空")
    if await SysUser.filter(username=username).exists():
        raise HTTPException(status_code=400, detail="用户名已被占用")
    user = await SysUser.create(
        username=username,
        password_hash=hash_password(req.password),
        nickname=(req.nickname or username).strip(),
        email=(req.email or "").strip(),
        role="admin" if req.role == "admin" else "user",
        enabled=True if req.enabled is None else bool(req.enabled),
    )
    return user_out(user)


@router.put("/{user_id}")
async def update_user(user_id: int, req: UserAdminReq, admin: SysUser = Depends(require_admin)) -> dict:
    user = await SysUser.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.role is not None:
        if user.role == "admin" and req.role != "admin" and await _admin_count() <= 1:
            raise HTTPException(status_code=400, detail="至少要保留一个管理员")
        user.role = "admin" if req.role == "admin" else "user"
    if req.enabled is not None:
        if user.id == admin.id and not req.enabled:
            raise HTTPException(status_code=400, detail="不能停用当前登录账号")
        user.enabled = bool(req.enabled)
    for field in ("nickname", "email"):
        value = getattr(req, field, None)
        if value is not None:
            setattr(user, field, value.strip())
    if req.password:
        if len(req.password) < 6:
            raise HTTPException(status_code=400, detail="密码至少 6 位")
        user.password_hash = hash_password(req.password)
    await user.save()
    return user_out(user)


@router.delete("/{user_id}")
async def delete_user(user_id: int, admin: SysUser = Depends(require_admin)) -> dict:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    user = await SysUser.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role == "admin" and await _admin_count() <= 1:
        raise HTTPException(status_code=400, detail="至少要保留一个管理员")
    await user.delete()
    await ChatSession.filter(user_id=user_id).delete()
    return {"ok": True, "message": f"已删除用户 {user.username}"}


async def _admin_count() -> int:
    return await SysUser.filter(role="admin").count()
