"""文档读取：多编码兜底，兼容国内常见的 GBK / GB18030 文档。"""
from __future__ import annotations

import io
import json
from pathlib import Path

ENCODINGS = ("utf-8", "utf-8-sig", "gbk", "gb18030")
SUPPORTED = {"txt", "md", "csv", "json", "pdf"}


def decode_bytes(data: bytes) -> tuple[str, str]:
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8(replace)"


def read_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def read_document(filename: str, data: bytes) -> tuple[str, str]:
    """返回 (正文, 说明)。正文为空时抛 ValueError，由接口层转成友好提示。"""
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext == "pdf":
        text = read_pdf(data)
        return text, "pdf 解析"
    if ext not in SUPPORTED:
        raise ValueError(f"暂不支持的文件类型：.{ext}（支持 txt/md/csv/json/pdf）")
    text, enc = decode_bytes(data)
    if ext == "json":
        try:
            text = _flatten_json(json.loads(text))
        except (ValueError, TypeError):
            pass
    text = text.strip()
    if not text:
        raise ValueError("文档内容为空")
    return text, f"{ext} / {enc}"


def _flatten_json(data, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                lines.append(_flatten_json(value, path))
            else:
                lines.append(f"{path}: {value}")
    elif isinstance(data, list):
        for index, item in enumerate(data):
            if isinstance(item, (dict, list)):
                lines.append(_flatten_json(item, f"{prefix}[{index}]"))
            else:
                lines.append(f"{prefix}[{index}]: {item}")
    else:
        lines.append(f"{prefix}: {data}")
    return "\n".join(line for line in lines if line.strip())
