"""冷启动默认配置：只从 .env / 进程环境读取，用于首次播种数据库配置。"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # fastapi-app/
DATA_DIR = BASE_DIR / ".data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _abs_sqlite(url: str) -> str:
    """把 sqlite:///.data/x.db 展成 .data 目录下的绝对路径，避免受启动目录影响。"""
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        name = PurePosixPath(url[len("sqlite:///") :].lstrip("/")).name
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return "sqlite:///" + (DATA_DIR / name).as_posix()
    return url


def async_sqlite_url(url: str) -> str:
    """SQLAlchemy 异步引擎要求显式 aiosqlite 方言（Tortoise 用 sqlite:// 即可）。"""
    if url.startswith("sqlite://") and "aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_host: str = "0.0.0.0"
    app_port: int = 9090
    app_secret_key: str = "plot-extraction-dev-secret"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    sys_db_url: str = "sqlite:///.data/sys.db"
    postgres_dsn: str = ""
    local_gis_url: str = "sqlite:///.data/gis_local.db"

    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_chat_model: str = "deepseek-chat"
    llm_temperature: float = 0.2
    llm_max_steps: int = 8

    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = "text-embedding-v3"
    embed_dim: int = 1024
    rag_top_k: int = 4
    chunk_size: int = 500
    chunk_overlap: int = 80

    tianditu_token: str = ""
    tianditu_use_sk: bool = False
    tianditu_sk: str = ""
    geovis_token: str = ""

    extract_grid_size: int = 300
    extract_simplify: float = 0.0001
    extract_min_area_mu: float = 0
    extract_default_center: str = "116.397,39.908"
    extract_default_extent_km: float = 3

    admin_username: str = "admin"
    admin_password: str = "admin123"

    @property
    def sys_db_url_abs(self) -> str:
        return _abs_sqlite(self.sys_db_url)

    @property
    def local_gis_url_abs(self) -> str:
        return _abs_sqlite(self.local_gis_url)

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


env = EnvSettings()
os.environ.setdefault("TZ", "Asia/Shanghai")
