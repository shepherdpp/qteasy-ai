# coding=utf-8
# ======================================
# File: session_attachments.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-24
# Desc:
# 会话级附件：类型白名单、体积限额、落盘与元数据规范化。
# 运行时消费（Ask/Plan/Agent）本阶段未接线。
# ======================================

"""会话附件工具。

``ConversationState.attachments`` 存元数据；文件在
``sessions/{stem}/attachments/``。本模块不做内容解析。
"""

from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .memory_store import MemoryStore

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SESSION_BYTES = 50 * 1024 * 1024

# 扩展名 → 默认 mime（上传未带 mime 时用）
_EXT_MIME: Dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".json": "application/json",
    ".csv": "text/csv",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".log": "text/plain",
    ".html": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".ts": "text/typescript",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

ALLOWED_EXTENSIONS = frozenset(_EXT_MIME.keys())

_ACCEPT_ATTR = ",".join(sorted(ALLOWED_EXTENSIONS))

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]+")


def file_input_accept() -> str:
    """浏览器 ``<input accept>`` 用的扩展名列表。"""

    return _ACCEPT_ATTR


def normalize_attachment(raw: Any) -> Optional[Dict[str, Any]]:
    """把一条附件字典收成权威形状；缺 ``source_path`` 则丢弃。

    Parameters
    ----------
    raw : Any
        原始条目。

    Returns
    -------
    dict or None
        含 ``id`` / ``source_path`` / ``display_name`` / ``mime_type`` /
        ``size_bytes``；有 ``summary`` 时保留。
    """

    if not isinstance(raw, dict):
        return None
    path = str(raw.get("source_path") or "").strip()
    if not path:
        return None
    att_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex[:12]
    display = str(raw.get("display_name") or "").strip() or Path(path).name
    mime = str(raw.get("mime_type") or "").strip()
    if not mime:
        mime = guess_mime(display)
    try:
        size = int(raw.get("size_bytes") or 0)
    except (TypeError, ValueError):
        size = 0
    if size < 0:
        size = 0
    out: Dict[str, Any] = {
        "id": att_id,
        "source_path": path,
        "display_name": display,
        "mime_type": mime,
        "size_bytes": size,
    }
    summary = raw.get("summary")
    if summary:
        out["summary"] = str(summary)
    return out


def guess_mime(filename: str) -> str:
    """按扩展名猜 mime；未知则 ``application/octet-stream``。"""

    ext = Path(str(filename or "")).suffix.lower()
    return _EXT_MIME.get(ext, "application/octet-stream")


def extension_allowed(filename: str) -> bool:
    """文件名扩展名是否在白名单。"""

    return Path(str(filename or "")).suffix.lower() in ALLOWED_EXTENSIONS


def session_attachments_dir(memory_store: MemoryStore, session_id: str) -> Path:
    """``sessions/{stem}/attachments`` 目录（不自动创建）。"""

    stem = MemoryStore.session_stem(session_id)
    return memory_store.sessions_dir / stem / "attachments"


def session_blob_dir(memory_store: MemoryStore, session_id: str) -> Path:
    """``sessions/{stem}/`` 旁路目录（附件等）。"""

    stem = MemoryStore.session_stem(session_id)
    return memory_store.sessions_dir / stem


def relative_source_path(memory_store: MemoryStore, absolute: Path) -> str:
    """相对 ``ai_home``（``base_dir``）的 posix 路径。"""

    abs_path = absolute.resolve()
    base = memory_store.base_dir.resolve()
    try:
        rel = abs_path.relative_to(base)
    except ValueError as exc:
        raise ValueError("Attachment path escapes memory root.") from exc
    return rel.as_posix()


def resolve_source_path(memory_store: MemoryStore, source_path: str) -> Path:
    """把相对 ``source_path`` 解析到 ``base_dir`` 下；越界则报错。"""

    base = memory_store.base_dir.resolve()
    candidate = (base / str(source_path or "").lstrip("/")).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Attachment path escapes memory root.") from exc
    return candidate


def session_attachment_bytes(attachments: List[Dict[str, Any]]) -> int:
    """会话已挂附件字节合计。"""

    total = 0
    for item in attachments or []:
        try:
            total += int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            continue
    return total


def validate_new_file(
    *,
    filename: str,
    size_bytes: int,
    existing: List[Dict[str, Any]],
) -> Optional[str]:
    """校验新文件；合法返回 ``None``，否则返回错误码。

    Parameters
    ----------
    filename : str
        原始文件名。
    size_bytes : int
        字节数。
    existing : list of dict
        当前会话附件。

    Returns
    -------
    str or None
        ``ATTACHMENT_TYPE_REJECTED`` / ``ATTACHMENT_TOO_LARGE`` /
        ``ATTACHMENT_SESSION_FULL``；通过为 ``None``。
    """

    if not extension_allowed(filename):
        return "ATTACHMENT_TYPE_REJECTED"
    if size_bytes < 0 or size_bytes > MAX_FILE_BYTES:
        return "ATTACHMENT_TOO_LARGE"
    if session_attachment_bytes(existing) + size_bytes > MAX_SESSION_BYTES:
        return "ATTACHMENT_SESSION_FULL"
    return None


def _stored_filename(display_name: str, att_id: str) -> str:
    """保留可读主干 + 短 id，避免覆盖。"""

    raw = Path(str(display_name or "file")).name
    stem = Path(raw).stem
    suffix = Path(raw).suffix.lower()
    safe_stem = _SAFE_NAME.sub("_", stem).strip("._") or "file"
    if len(safe_stem) > 80:
        safe_stem = safe_stem[:80]
    short = (att_id or uuid.uuid4().hex)[:8]
    return f"{safe_stem}_{short}{suffix}"


def save_attachment_bytes(
    memory_store: MemoryStore,
    session_id: str,
    *,
    filename: str,
    data: bytes,
    mime_type: str = "",
    existing: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """校验、落盘并返回规范化条目。

    Parameters
    ----------
    memory_store : MemoryStore
        内存根。
    session_id : str
        会话 id。
    filename : str
        显示用原始文件名。
    data : bytes
        文件内容。
    mime_type : str, optional
        客户端 mime；空则按扩展名猜。
    existing : list of dict, optional
        当前附件列表（限额合计）。

    Returns
    -------
    (dict, None) or (None, error_code)
        成功为条目；失败为错误码。
    """

    display = Path(str(filename or "file")).name or "file"
    size = len(data)
    code = validate_new_file(
        filename=display,
        size_bytes=size,
        existing=list(existing or []),
    )
    if code:
        return None, code
    att_id = uuid.uuid4().hex[:12]
    stored = _stored_filename(display, att_id)
    dest_dir = session_attachments_dir(memory_store, session_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / stored
    dest.write_bytes(data)
    mime = str(mime_type or "").strip() or guess_mime(display)
    try:
        source_path = relative_source_path(memory_store, dest)
    except ValueError:
        try:
            dest.unlink()
        except OSError:
            pass
        return None, "ATTACHMENT_PATH_INVALID"
    return (
        {
            "id": att_id,
            "source_path": source_path,
            "display_name": display,
            "mime_type": mime,
            "size_bytes": size,
        },
        None,
    )


def remove_attachment_files(
    memory_store: MemoryStore,
    entry: Dict[str, Any],
) -> None:
    """删除一条附件对应的磁盘文件（忽略缺失）。"""

    path_str = str((entry or {}).get("source_path") or "").strip()
    if not path_str:
        return
    try:
        path = resolve_source_path(memory_store, path_str)
    except ValueError:
        return
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def remove_session_blob_dir(memory_store: MemoryStore, session_id: str) -> None:
    """删除 ``sessions/{stem}/`` 旁路目录（含 attachments）。"""

    blob = session_blob_dir(memory_store, session_id)
    if blob.is_dir():
        shutil.rmtree(blob, ignore_errors=True)
