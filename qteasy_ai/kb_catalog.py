# coding=utf-8
# ======================================
# File: kb_catalog.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-07
# Desc:
# 从策展地图编译问句目录与 type 索引。
# 不读取 Sphinx / 手册正文。
# ======================================

"""官方 KB 策展地图的 compile。

真源是 ``kb/_source/curation_map.json``。本模块只校验并生成目录，
不从手册抽取叙事。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping

_GENERATED_BY = "scripts/compile_kb_catalog.py"
_EDGE_PUNCT_RE = re.compile(r"^[?？!！.。]+|[?？!！.。]+$")
# 只去掉汉字与拉丁字母/数字交界上的空格，英文单词之间的空格保留。
_CJK_LATIN_SPACE_RE = re.compile(r"([\u4e00-\u9fff])\s+([a-z0-9])")
_LATIN_CJK_SPACE_RE = re.compile(r"([a-z0-9])\s+([\u4e00-\u9fff])")


@dataclass
class CatalogArtifacts:
    """compile 的三份内存结果，由脚本写盘。"""

    question_catalog: Dict[str, Any]
    type_index: Dict[str, Any]
    catalog_markdown: str


def normalize_question(text: str) -> str:
    """规范化问句，供目录精确匹配。

    Parameters
    ----------
    text : str
        原始问句。

    Returns
    -------
    str
        strip、拉丁小写、折叠连续空白、去掉首尾 ``?？!！.。``，
        并去掉汉字与拉丁字母/数字交界上的空格。
    """

    collapsed = re.sub(r"\s+", " ", (text or "").strip().lower())
    stripped = _EDGE_PUNCT_RE.sub("", collapsed).strip()
    stripped = _CJK_LATIN_SPACE_RE.sub(r"\1\2", stripped)
    stripped = _LATIN_CJK_SPACE_RE.sub(r"\1\2", stripped)
    return stripped.strip()


def dumps_catalog_json(payload: Mapping[str, Any]) -> str:
    """把生成物字典格式化成稳定 JSON 文本。

    Parameters
    ----------
    payload : mapping
        问句目录或 type 索引。

    Returns
    -------
    str
        UTF-8 JSON，键排序，末尾换行。
    """

    return json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def compile_catalog(
        *,
        kb_dir: Path,
        map_path: Path,
        qteasy_root: Path,
) -> CatalogArtifacts:
    """校验策展地图与 JSON，并生成目录、type 索引和 catalog 正文。

    Parameters
    ----------
    kb_dir : Path
        官方 ``kb/`` 目录（只读其中的 ``*.json``）。
    map_path : Path
        策展地图 JSON。
    qteasy_root : Path
        qteasy 仓库根。非空 ``manual_anchor`` 只在此根下做 ``is_file()``。

    Returns
    -------
    CatalogArtifacts
        问句目录、type 索引、catalog Markdown。

    Raises
    ------
    ValueError
        地图与 JSON 不一致、问句重复、relation 悬空，或锚点文件不存在。
    """

    from qteasy_ai.knowledge_base import (
        _KB_ENTRY_TYPES,
        _parse_manual_anchor,
        _parse_relations,
        _require_entry_type,
    )

    entries = _load_json_entries(kb_dir)
    rows = _load_map_rows(map_path)
    _require_same_ids(rows, entries)

    questions: Dict[str, str] = {}
    by_type: Dict[str, List[str]] = {entry_type: [] for entry_type in sorted(_KB_ENTRY_TYPES)}
    rendered_rows: List[Dict[str, Any]] = []

    for entry_id in sorted(entries):
        row = rows[entry_id]
        entry = entries[entry_id]
        entry_type = _require_same_type(entry_id, row, entry, _require_entry_type)
        anchor = _require_same_anchor(entry_id, row, entry, _parse_manual_anchor)
        relations = _require_same_relations(entry_id, row, entry, _parse_relations)
        _require_anchor_file(entry_id, anchor, qteasy_root)
        _collect_questions(entry_id, row.get("questions"), questions)
        by_type[entry_type].append(entry_id)
        rendered_rows.append({
            "id": entry_id,
            "type": entry_type,
            "manual_anchor": anchor,
            "relations": relations,
            "questions": list(row["questions"]),
        })

    known = set(entries)
    for entry_id in sorted(entries):
        for item in _parse_relations(entry_id, entries[entry_id]):
            target = item["to"]
            if target not in known:
                raise ValueError(
                    f"KB entry {entry_id!r} relation target {target!r} does not exist"
                )

    for entry_type in by_type:
        by_type[entry_type].sort()

    return CatalogArtifacts(
        question_catalog={
            "_do_not_edit": True,
            "_generated": _GENERATED_BY,
            "questions": {key: questions[key] for key in sorted(questions)},
        },
        type_index={
            "_do_not_edit": True,
            "_generated": _GENERATED_BY,
            "by_type": by_type,
        },
        catalog_markdown=_render_catalog_markdown(rendered_rows),
    )


def _load_json_entries(kb_dir: Path) -> Dict[str, Dict[str, Any]]:
    """读取 ``kb/*.json``。子目录里的地图和生成物不算条目。"""

    entries: Dict[str, Dict[str, Any]] = {}
    for path in sorted(kb_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload.get("id"):
            raise ValueError(f"KB file {path.name} is not an entry with an id")
        entry_id = str(payload["id"])
        if entry_id in entries:
            raise ValueError(f"KB entry {entry_id!r} is duplicated")
        entries[entry_id] = payload
    return entries


def _load_map_rows(map_path: Path) -> Dict[str, Dict[str, Any]]:
    """读取策展地图，按 id 索引。"""

    payload = json.loads(map_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValueError("KB curation map must contain an entries list")
    rows: Dict[str, Dict[str, Any]] = {}
    for row in payload["entries"]:
        if not isinstance(row, dict) or not row.get("id"):
            raise ValueError("KB curation map row is missing id")
        entry_id = str(row["id"])
        if entry_id in rows:
            raise ValueError(f"KB curation map duplicates id {entry_id!r}")
        rows[entry_id] = row
    return rows


def _require_same_ids(
        rows: Mapping[str, Any],
        entries: Mapping[str, Any],
) -> None:
    """地图 id 与 JSON id 必须双向一致。"""

    if set(rows) == set(entries):
        return
    missing_json = sorted(set(rows) - set(entries))
    missing_map = sorted(set(entries) - set(rows))
    raise ValueError(
        "KB curation map and JSON ids differ; "
        f"missing JSON: {missing_json}; missing map: {missing_map}"
    )


def _require_same_type(
        entry_id: str,
        row: Mapping[str, Any],
        entry: Mapping[str, Any],
        require_type: Callable[[str, Mapping[str, Any]], str],
) -> str:
    """地图与 JSON 的 type 必须相同。"""

    map_type = require_type(entry_id, row)
    json_type = require_type(entry_id, entry)
    if map_type != json_type:
        raise ValueError(
            f"KB entry {entry_id!r} type mismatch: map {map_type!r} vs JSON {json_type!r}"
        )
    return map_type


def _require_same_anchor(
        entry_id: str,
        row: Mapping[str, Any],
        entry: Mapping[str, Any],
        parse_anchor: Callable[[str, Mapping[str, Any]], str],
) -> str:
    """地图与 JSON 的 manual_anchor 必须相同。"""

    map_anchor = parse_anchor(entry_id, row)
    json_anchor = parse_anchor(entry_id, entry)
    if map_anchor != json_anchor:
        raise ValueError(
            f"KB entry {entry_id!r} manual_anchor mismatch: "
            f"map {map_anchor!r} vs JSON {json_anchor!r}"
        )
    return map_anchor


def _require_same_relations(
        entry_id: str,
        row: Mapping[str, Any],
        entry: Mapping[str, Any],
        parse_relations: Callable[[str, Mapping[str, Any]], List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """地图与 JSON 的 relations 必须相同。"""

    map_relations = parse_relations(entry_id, row)
    json_relations = parse_relations(entry_id, entry)
    if map_relations != json_relations:
        raise ValueError(
            f"KB entry {entry_id!r} relations mismatch: "
            f"map {map_relations!r} vs JSON {json_relations!r}"
        )
    return map_relations


def _require_anchor_file(entry_id: str, anchor: str, qteasy_root: Path) -> None:
    """非空手册锚必须指向 qteasy 仓内已有文件。不读取文件内容。"""

    if not anchor:
        return
    if not (qteasy_root / anchor).is_file():
        raise ValueError(
            f"KB entry {entry_id!r} manual_anchor file does not exist: {anchor}"
        )


def _collect_questions(entry_id: str, raw_questions: Any, questions: Dict[str, str]) -> None:
    """把代表问句规范化后写入目录。同一 id 撞键合并，不同 id 撞键失败。"""

    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError(f"KB entry {entry_id!r} has no representative questions")
    for question in raw_questions:
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"KB entry {entry_id!r} has an empty question")
        key = normalize_question(question)
        if not key:
            raise ValueError(f"KB entry {entry_id!r} question normalizes to empty")
        previous = questions.get(key)
        if previous is not None and previous != entry_id:
            raise ValueError(
                f"Duplicate normalized question {key!r} for {previous!r} and {entry_id!r}"
            )
        questions[key] = entry_id


def _render_catalog_markdown(rows: List[Dict[str, Any]]) -> str:
    """生成给人看的目录。只含地图字段，不含叙事。"""

    lines = [
        "<!-- Generated by scripts/compile_kb_catalog.py. Do not edit. -->",
        "",
        "# 官方 KB 问句目录",
        "",
        "由策展地图编译生成。只列 id、type、手册锚、代表问句与 relations。",
        "",
    ]
    for row in rows:
        lines.append(f"## {row['id']}")
        lines.append("")
        lines.append(f"- type: {row['type']}")
        lines.append(f"- manual_anchor: {row['manual_anchor']}")
        relations = row["relations"]
        if relations:
            lines.append("- relations:")
            for item in relations:
                lines.append(f"  - {item['rel']} -> {item['to']}")
        else:
            lines.append("- relations: []")
        lines.append("- questions:")
        for question in row["questions"]:
            lines.append(f"  - {question}")
        lines.append("")
    return "\n".join(lines)
