# coding=utf-8
# ======================================
# File: slot_decl.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-30
# Desc:
# 按 Job slots 声明问、拒、拆。规划器重判与控件写入前共用。
# ======================================

"""解释 Job ``slots`` 声明。不从被拒原文反推该改哪一格。"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional

from .skills.research_factor_ic import _share_codes

_ONE_SPLIT = re.compile(r"\s*(?:,|，|\+|\band\b)\s*", flags=re.IGNORECASE)
_DATE_TEXT = re.compile(r"^20\d{6}$")


def interpret_declared_slots(
    declarations: List[Dict[str, Any]],
    values: Dict[str, Any],
    *,
    is_history_column: Callable[[str], bool],
) -> Dict[str, Any]:
    """按声明检查一组槽值。

    每个槽先按 ``cardinality`` 切分。单值槽切出多段时，只决定拆开或拒绝本格，
    然后停，不用原文做 ``distinct_from``。单值通过 ``value_kind`` 之后，
    ``distinct_from`` 只比较两边都已通过的单值。

    Parameters
    ----------
    declarations : list of dict
        该 Job 的 ``slots``。空名单表示本函数不发问。
    values : dict
        当前槽值，键为槽名。
    is_history_column : callable
        ``history_panel_column`` 的检查。复用规划器里的列名判断。

    Returns
    -------
    dict
        ``values`` 为已通过的单值或列表原文；``pending`` 为仍要问的槽
        （含 ``name`` / ``label`` / ``hint`` / ``error``）；``patches`` 仅为
        成功拆开时写回的两格。

    Examples
    --------
    >>> verdict = interpret_declared_slots([], {}, is_history_column=lambda _name: False)
    >>> verdict["pending"]
    []
    """

    rows = [dict(item) for item in (declarations or []) if isinstance(item, dict) and item.get("name")]
    if not rows:
        return {"values": {}, "pending": [], "patches": {}}
    working = {str(item["name"]): _text(values.get(str(item["name"]))) for item in rows}
    pending: List[Dict[str, Any]] = []
    passed: Dict[str, str] = {}
    patches: Dict[str, str] = {}
    for decl in rows:
        name = str(decl["name"])
        text = working.get(name) or ""
        if not text:
            pending.append(_pending(decl, ""))
            continue
        if str(decl.get("cardinality") or "one") == "many":
            _take_many(decl, text, pending, passed, is_history_column)
            continue
        if str(decl.get("cardinality") or "one") != "one":
            pending.append(_pending(decl, f"{text!r} cannot be accepted for this field."))
            continue
        segments = _split_one(text)
        if len(segments) > 1:
            assigned = _take_two_segments(
                decl,
                segments,
                rows,
                working,
                passed,
                patches,
                is_history_column,
            )
            if not assigned:
                pending.append(_pending(decl, f"{text!r} is not one value for this field."))
            continue
        normalized = _accept_one(decl, segments[0] if segments else text, is_history_column)
        if normalized is None:
            pending.append(_pending(decl, _kind_error(decl, text)))
            continue
        passed[name] = normalized
        working[name] = normalized
    for decl in rows:
        other_name = str(decl.get("distinct_from") or "").strip()
        name = str(decl["name"])
        if not other_name or name not in passed or other_name not in passed:
            continue
        if passed[name].casefold() != passed[other_name].casefold():
            continue
        other = _decl_by_name(rows, other_name)
        other_label = str((other or {}).get("label") or other_name)
        pending.append(
            _pending(decl, f"{passed[name]!r} must differ from {other_label}.")
        )
        passed.pop(name, None)
        working[name] = _text(values.get(name))
    pending = [item for item in pending if item["name"] not in passed]
    return {"values": dict(passed), "pending": pending, "patches": patches}


def clarification_prompt(pending: List[Dict[str, Any]]) -> str:
    """卡片正文只点名被拒的格子。填法留在各格的 hint / error。

    Parameters
    ----------
    pending : list of dict
        ``interpret_declared_slots`` 的 ``pending``。

    Returns
    -------
    str
        英文局面说明。
    """

    rejected = [item for item in pending if str(item.get("error") or "").strip()]
    missing = [item for item in pending if not str(item.get("error") or "").strip()]
    parts: List[str] = []
    if missing:
        parts.append("Some fields are still missing.")
    if rejected:
        labels = ", ".join(str(item.get("label") or item.get("name") or "") for item in rejected)
        parts.append(f"Rejected: {labels}.")
    return " ".join(parts).strip() or "Some fields are still missing."


def _take_many(
    decl: Dict[str, Any],
    text: str,
    pending: List[Dict[str, Any]],
    passed: Dict[str, str],
    is_history_column: Callable[[str], bool],
) -> None:
    """列表槽：与 ``_share_codes`` 同一切法，不走单值两段拆分。"""

    name = str(decl["name"])
    kind = str(decl.get("value_kind") or "")
    codes = _share_codes(text)
    minimum = int(decl.get("min_count") or 1)
    if not _kind_ok(kind, text, is_history_column):
        pending.append(_pending(decl, _kind_error(decl, text)))
        return
    if len(codes) < minimum:
        pending.append(_pending(decl, f"{text!r} needs at least {minimum} entries."))
        return
    passed[name] = text


def _take_two_segments(
    decl: Dict[str, Any],
    segments: List[str],
    rows: List[Dict[str, Any]],
    working: Dict[str, str],
    passed: Dict[str, str],
    patches: Dict[str, str],
    is_history_column: Callable[[str], bool],
) -> bool:
    """恰好一个空着的同 kind 单值伙伴，且两段都合法、彼此不同，才拆开。"""

    if len(segments) != 2:
        return False
    kind = str(decl.get("value_kind") or "")
    left = _accept_one(decl, segments[0], is_history_column)
    right = _accept_one(decl, segments[1], is_history_column)
    if left is None or right is None or left.casefold() == right.casefold():
        return False
    partners = [
        item
        for item in rows
        if str(item.get("name")) != str(decl["name"])
        and str(item.get("cardinality") or "one") == "one"
        and str(item.get("value_kind") or "") == kind
        and not str(working.get(str(item["name"])) or "").strip()
    ]
    if len(partners) != 1:
        return False
    partner = str(partners[0]["name"])
    current = str(decl["name"])
    working[current] = left
    working[partner] = right
    passed[current] = left
    passed[partner] = right
    patches[current] = left
    patches[partner] = right
    return True


def _accept_one(
    decl: Dict[str, Any],
    text: str,
    is_history_column: Callable[[str], bool],
) -> Optional[str]:
    """单值通过 value_kind 时返回写入用的文本，否则 ``None``。"""

    kind = str(decl.get("value_kind") or "")
    raw = _text(text)
    if not raw or not _kind_ok(kind, raw, is_history_column):
        return None
    if kind == "date":
        return _normalize_date(raw)
    return raw


def _kind_ok(kind: str, text: str, is_history_column: Callable[[str], bool]) -> bool:
    """三种已知 kind。未知 kind 不放行。"""

    if kind == "date":
        return _normalize_date(text) is not None
    if kind == "symbol_list":
        return bool(_share_codes(text))
    if kind == "history_panel_column":
        try:
            return bool(is_history_column(text))
        except Exception:
            return False
    return False


def _kind_error(decl: Dict[str, Any], text: str) -> str:
    """失败文案引用原文，不把例子写成一个格子里的两列。"""

    kind = str(decl.get("value_kind") or "")
    if kind == "date":
        return f"{text!r} is not a YYYYMMDD date."
    if kind == "symbol_list":
        minimum = int(decl.get("min_count") or 1)
        return f"{text!r} needs at least {minimum} entries."
    if kind == "history_panel_column":
        return f"{text!r} is not a local history column."
    return f"{text!r} cannot be accepted for this field."


def _pending(decl: Dict[str, Any], error: str) -> Dict[str, Any]:
    """一张待问槽。``error`` 为空表示仅仅缺值。"""

    return {
        "name": str(decl.get("name") or ""),
        "label": str(decl.get("label") or decl.get("name") or ""),
        "hint": str(decl.get("hint") or ""),
        "error": str(error or ""),
    }


def _decl_by_name(rows: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """按槽名找声明。"""

    for item in rows:
        if str(item.get("name") or "") == name:
            return item
    return None


def _split_one(text: str) -> List[str]:
    """单值槽按逗号、and、加号切开。"""

    return [part.strip() for part in _ONE_SPLIT.split(_text(text)) if part.strip()]


def _normalize_date(text: str) -> Optional[str]:
    """``YYYYMMDD`` 或带分隔符的同一天。非法则 ``None``。"""

    compact = _text(text).replace("-", "").replace("/", "")
    if not _DATE_TEXT.fullmatch(compact):
        return None
    try:
        _dt.datetime.strptime(compact, "%Y%m%d")
    except ValueError:
        return None
    return compact


def _text(value: Any) -> str:
    """槽值转成去空白的字符串。"""

    if value is None:
        return ""
    return str(value).strip()
