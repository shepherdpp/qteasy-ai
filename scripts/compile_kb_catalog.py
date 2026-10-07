# coding=utf-8
# ======================================
# File: compile_kb_catalog.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-07
# Desc:
# 编译官方 KB 问句目录与 type 索引。
# 禁止手改生成物，禁止从 Sphinx 抽叙事。
# ======================================

"""把策展地图编译进 ``qteasy_ai/kb/_generated/``。

用法（在 qteasy-ai 仓库根）::

    /opt/anaconda3/envs/py39/bin/python scripts/compile_kb_catalog.py

非空手册锚默认到兄弟目录 ``../qteasy`` 做存在性检查。
可用环境变量 ``QTEASY_ROOT`` 覆盖。不读取锚点文件正文。
"""

from __future__ import annotations

import os
from pathlib import Path

from qteasy_ai.kb_catalog import compile_catalog, dumps_catalog_json


def main() -> int:
    """编译并覆盖生成物。

    Returns
    -------
    int
        成功时为 0。
    """

    repo = Path(__file__).resolve().parents[1]
    kb_dir = repo / "qteasy_ai" / "kb"
    map_path = kb_dir / "_source" / "curation_map.json"
    out_dir = kb_dir / "_generated"
    qteasy_root = Path(os.environ["QTEASY_ROOT"]) if os.environ.get("QTEASY_ROOT") else repo.parent / "qteasy"
    artifacts = compile_catalog(kb_dir=kb_dir, map_path=map_path, qteasy_root=qteasy_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "question_catalog.json").write_text(
        dumps_catalog_json(artifacts.question_catalog),
        encoding="utf-8",
    )
    (out_dir / "type_index.json").write_text(
        dumps_catalog_json(artifacts.type_index),
        encoding="utf-8",
    )
    (out_dir / "CATALOG.md").write_text(artifacts.catalog_markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
