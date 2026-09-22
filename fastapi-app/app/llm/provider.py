"""模型工厂：只依赖 langchain-openai，靠 base_url 切换 OpenAI / DeepSeek / 通义 / Ollama。

配置改完即重建实例（热生效），未配置模型时返回 None，由上层走降级路径。
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config.runtime import runtime

log = logging.getLogger(__name__)

LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def llm_configured() -> bool:
    base = runtime.chat_base_url
    return bool(base and runtime.get_str("llm.chat_model") and (runtime.get_str("llm.api_key") or any(h in base for h in LOCAL_HOSTS)))


def chat_model(temperature: float | None = None, timeout: int = 120) -> ChatOpenAI | None:
    if not llm_configured():
        return None
    return ChatOpenAI(
        base_url=runtime.chat_base_url,
        api_key=runtime.get_str("llm.api_key") or "not-needed",
        model=runtime.get_str("llm.chat_model"),
        temperature=runtime.get_float("llm.temperature", 0.2) if temperature is None else temperature,
        timeout=timeout,
        max_retries=1,
    )


def embedding_model() -> OpenAIEmbeddings | None:
    """嵌入层关闭 tiktoken 预切分：通义 / DeepSeek / Ollama 等兼容接口不支持它，不关会直接报错。"""
    base = runtime.embed_base_url
    model = runtime.get_str("embed.model")
    key = runtime.embed_api_key
    if not base or not model or (not key and not any(h in base for h in LOCAL_HOSTS)):
        return None
    return OpenAIEmbeddings(
        base_url=base,
        api_key=key or "not-needed",
        model=model,
        check_embedding_ctx_length=False,
        timeout=60,
        max_retries=1,
    )


async def test_chat() -> dict[str, Any]:
    model = chat_model(temperature=0.0, timeout=45)
    if model is None:
        return {"ok": False, "message": "未配置大模型（Base URL / API Key / 模型名）"}
    import time

    started = time.perf_counter()
    try:
        reply = await model.ainvoke("请用四个字回答：你现在在线吗？")
        text = getattr(reply, "content", str(reply))
        return {
            "ok": True,
            "model": runtime.get_str("llm.chat_model"),
            "base_url": runtime.chat_base_url,
            "reply": str(text)[:200],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:300]}", "base_url": runtime.chat_base_url}


async def test_embedding() -> dict[str, Any]:
    embeddings = embedding_model()
    if embeddings is None:
        return {"ok": False, "message": "未配置嵌入模型（Base URL / API Key / 模型名）"}
    try:
        vector = await embeddings.aembed_query("连通性测试")
        return {
            "ok": True,
            "model": runtime.get_str("embed.model"),
            "dim": len(vector),
            "configured_dim": runtime.get_int("embed.dim"),
            "match": len(vector) == runtime.get_int("embed.dim"),
        }
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:300]}"}
