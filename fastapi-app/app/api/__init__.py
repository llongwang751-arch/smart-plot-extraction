"""API 路由汇总。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, chat, config, dashboard, extract, knowledge, maps, plots, records, users

api_router = APIRouter()
for module in (auth, users, config, plots, knowledge, extract, records, chat, maps, dashboard):
    api_router.include_router(module.router)
