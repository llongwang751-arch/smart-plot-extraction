"""业务库表（MySQL / SQLite，Tortoise ORM）：账号、系统配置、知识库元数据、对话记录。

空间几何与向量不放这里，由 GIS 存储层负责。
"""
from __future__ import annotations

from tortoise import fields
from tortoise.models import Model


class SysConfig(Model):
    id = fields.IntField(primary_key=True)
    key = fields.CharField(max_length=128, unique=True)
    value = fields.TextField(default="")
    group = fields.CharField(max_length=64, default="")
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "sys_config"


class SysUser(Model):
    id = fields.IntField(primary_key=True)
    username = fields.CharField(max_length=64, unique=True)
    password_hash = fields.CharField(max_length=256)
    nickname = fields.CharField(max_length=64, default="")
    email = fields.CharField(max_length=128, default="")
    phone = fields.CharField(max_length=32, default="")
    role = fields.CharField(max_length=16, default="user")  # admin | user
    enabled = fields.BooleanField(default=True)
    last_login_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "sys_user"
        ordering = ["-created_at"]


class KbDocument(Model):
    """知识库文档元数据；原文与向量存在 GIS 存储层，这里只留台账。"""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=256)
    source = fields.CharField(max_length=16, default="upload")  # upload | text
    file_ext = fields.CharField(max_length=16, default="")
    size_bytes = fields.IntField(default=0)
    char_count = fields.IntField(default=0)
    chunk_count = fields.IntField(default=0)
    status = fields.CharField(max_length=16, default="pending")  # pending|ready|failed
    error = fields.CharField(max_length=512, default="")
    owner_id = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "kb_document"
        ordering = ["-created_at"]


class ChatSession(Model):
    id = fields.IntField(primary_key=True)
    user_id = fields.IntField(default=0)
    title = fields.CharField(max_length=128, default="新会话")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "chat_session"
        ordering = ["-updated_at"]


class ChatMessage(Model):
    id = fields.IntField(primary_key=True)
    session_id = fields.IntField(default=0, index=True)
    role = fields.CharField(max_length=16)  # user | assistant
    content = fields.TextField(default="")
    tool_trace = fields.TextField(default="[]")  # [{name, args, result, elapsed}]
    sources = fields.TextField(default="[]")  # [{doc, text, score}]
    geojson = fields.TextField(default="")  # Agent 产出的地块，前端直接上图
    elapsed_ms = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chat_message"
        ordering = ["id"]


MODEL_MODULES = ["app.models.sys_tables"]
