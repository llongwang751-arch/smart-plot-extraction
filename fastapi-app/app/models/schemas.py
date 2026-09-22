"""请求/响应模型（Pydantic v2）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginReq(BaseModel):
    username: str
    password: str


class RegisterReq(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)
    nickname: str = ""
    email: str = ""


class ProfileReq(BaseModel):
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None


class PasswordReq(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class UserAdminReq(BaseModel):
    username: str | None = None
    password: str | None = None
    nickname: str | None = None
    email: str | None = None
    role: str | None = None
    enabled: bool | None = None


class PlotReq(BaseModel):
    code: str = ""
    name: str = ""
    land_type: str = "未利用地"
    region: str = ""
    owner: str = ""
    geometry: Any = None


class PlotUpdateReq(BaseModel):
    code: str | None = None
    name: str | None = None
    land_type: str | None = None
    region: str | None = None
    owner: str | None = None
    geometry: Any = None


class ExtractReq(BaseModel):
    query: str = ""
    mode: str = Field(default="smart", pattern="^(smart|space)$")
    aoi: Any = None
    land_types: list[str] = Field(default_factory=list)
    min_area_mu: float = 0
    save: bool = True


class SavePlotsReq(BaseModel):
    task_id: int = 0
    features: list[dict[str, Any]] = Field(default_factory=list)
    region: str = ""


class SampleReq(BaseModel):
    count: int = Field(default=60, ge=1, le=500)
    overwrite: bool = False
    seed: int | None = None


class TaskFromResultReq(BaseModel):
    geojson: Any = None
    statistics: Any = None
    analysis: str = ""
    trace: list[dict[str, Any]] = Field(default_factory=list)
    query: str = ""
    mode: str = "space"
    aoi: Any = None
    land_types: list[str] = Field(default_factory=list)
    min_area_mu: float = 0
    engine: str = ""
    elapsed_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


class KbTextReq(BaseModel):
    name: str
    text: str


class KbSearchReq(BaseModel):
    query: str
    k: int | None = None


class ConfigUpdateReq(BaseModel):
    values: dict[str, Any]


class TestReq(BaseModel):
    target: str = Field(pattern="^(llm|embed|sys_db|tiles|gis)$")


class ChatReq(BaseModel):
    message: str
    session_id: int = 0


class SessionTitleReq(BaseModel):
    title: str


class AnswerOut(BaseModel):
    answer: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    plots: Any = None
    calls: list[dict[str, Any]] = Field(default_factory=list)
    via: str = ""
    steps: int = 0
    elapsed_ms: int = 0
    session_id: int = 0
    message_id: int = 0
