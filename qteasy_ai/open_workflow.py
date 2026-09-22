# coding=utf-8
# ======================================
# File: open_workflow.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# 用户 KB 确认写入；系统 Job open 的 DAG 在 planner。
# ======================================

"""用户 KB 显式写入。系统 Job ``open`` 合法边 DAG 在 ``planner._compose_open_dag``。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def write_confirmed_note(store: Any, draft: Dict[str, Any]) -> str:
    """确认后写入 raw/ 并 compile。

    Parameters
    ----------
    store : MemoryStore
        带 ``user_kb_dir`` 的存储。
    draft : dict
        须含 ``relpath``（``raw/...``）与 ``body``。

    Returns
    -------
    str
        写入后的绝对路径。
    """

    rel = str(draft.get("relpath") or "")
    if not rel.startswith("raw/"):
        raise ValueError("KB write path must stay under raw/.")
    path = Path(store.user_kb_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(draft.get("body") or ""), encoding="utf-8")
    store.compile_user_kb()
    return str(path)
