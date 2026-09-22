"""账号接口：登录不选角色，由后端按账号判定；凭证由服务端签发。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.core.deps import assert_self_or_admin, get_current_user, user_out
from app.core.security import create_token, hash_password, verify_password
from app.models.schemas import LoginReq, PasswordReq, ProfileReq, RegisterReq
from app.models.sys_tables import SysUser

router = APIRouter(prefix="/api/auth", tags=["账号"])


@router.post("/login")
async def login(req: LoginReq) -> dict:
    user = await SysUser.get_or_none(username=req.username.strip())
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.enabled:
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    user.last_login_at = datetime.now()
    await user.save()
    return {"token": create_token(user.id, user.username, user.role), "user": user_out(user)}


@router.post("/register")
async def register(req: RegisterReq) -> dict:
    username = req.username.strip()
    if username.lower() in {"admin", "administrator", "root"}:
        raise HTTPException(status_code=400, detail="该用户名被保留")
    if await SysUser.filter(username=username).exists():
        raise HTTPException(status_code=400, detail="用户名已被占用")
    user = await SysUser.create(
        username=username,
        password_hash=hash_password(req.password),
        nickname=req.nickname.strip() or username,
        email=req.email.strip(),
        role="user",
        enabled=True,
    )
    return {"token": create_token(user.id, user.username, user.role), "user": user_out(user)}


@router.get("/me")
async def me(user: SysUser = Depends(get_current_user)) -> dict:
    return user_out(user)


@router.put("/profile")
async def update_profile(req: ProfileReq, user: SysUser = Depends(get_current_user)) -> dict:
    assert_self_or_admin(user.id, user)
    for field in ("nickname", "email", "phone"):
        value = getattr(req, field, None)
        if value is not None:
            setattr(user, field, value.strip())
    await user.save()
    return user_out(user)


@router.post("/password")
async def change_password(req: PasswordReq, user: SysUser = Depends(get_current_user)) -> dict:
    if not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.password_hash = hash_password(req.new_password)
    await user.save()
    return {"ok": True, "message": "密码已更新，请使用新密码重新登录"}
