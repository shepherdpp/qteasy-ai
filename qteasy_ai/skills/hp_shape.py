# coding=utf-8
# ======================================
# File: hp_shape.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 面板查看之后的整形原子：切片、删列、改名、填补、
# 丢空、重采样、赋值、对齐与合并。
# ======================================

"""HistoryPanel 整形技能。不执行任意 Python。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Sequence

import numpy as np
import pandas as pd
from qteasy.history import HistoryPanel

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed, panel_from_upstream
from .preview_rows import tabular_preview_rows

_FILL_METHODS = ("ffill", "bfill", "fillna")


def _detect_month_rule() -> str:
    """当前 pandas 接受 ``ME`` 时用月末别名，否则退回 ``M``。"""

    probe = pd.Series([1.0], index=pd.to_datetime(["2024-01-31"]))
    try:
        probe.resample("ME").last()
    except (ValueError, TypeError, NotImplementedError):
        return "M"
    return "ME"


_MONTH_RULE = _detect_month_rule()


def _date_key(value: Any) -> str:
    """把日期收成 ``YYYYMMDD``。"""

    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y%m%d")
        except (TypeError, ValueError):
            pass
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:8]


def _normalize_rule(rule: str) -> str:
    """``w`` 映射为周五结束的周，``m`` 映射为日历月末。"""

    token = str(rule or "").strip()
    if token == "w":
        return "W-FRI"
    if token == "m":
        return _MONTH_RULE
    return token


def _panel_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], panel: Any, **extra: Any) -> dict:
    """成功结果。完整面板留在 payload，预览只给有限行。"""

    payload = {"panel": panel, "preview_rows": tabular_preview_rows(panel)}
    payload.update(extra)
    result = SkillResult(
        ok=True,
        skill_name=metadata.name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        metrics={
            "n_rows": int(panel.row_count),
            "n_shares": len(list(panel.shares)),
            "n_htypes": len(list(panel.htypes)),
        },
        data_summary={"htypes": [str(name) for name in panel.htypes], "shares": [str(name) for name in panel.shares]},
        payload=payload,
    )
    return result.to_dict()


def _require_panel(metadata: SkillMetadata, upstream_payload: Any, inputs_echo: Dict[str, Any]) -> Any:
    """取出上游面板。没有时返回失败字典。"""

    panel = panel_from_upstream(upstream_payload if isinstance(upstream_payload, dict) else None)
    if panel is None:
        return failed(
            metadata.name,
            "HP_PANEL_MISSING",
            "A HistoryPanel from the previous step is required.",
            inputs_echo,
        )
    return panel


def _two_panels(
    metadata: SkillMetadata,
    upstream_payload: Any,
    upstream_payloads: Any,
    inputs_echo: Dict[str, Any],
) -> Any:
    """按依赖顺序取两块面板。"""

    found = []
    if isinstance(upstream_payloads, list):
        for item in upstream_payloads:
            panel = panel_from_upstream(item if isinstance(item, dict) else None)
            if panel is not None:
                found.append(panel)
    if len(found) < 2:
        return failed(
            metadata.name,
            "HP_PANELS_REQUIRED",
            "Two HistoryPanels from previous steps are required.",
            inputs_echo,
        )
    return found[0], found[1]


def _run_panel(metadata: SkillMetadata, inputs_echo: Dict[str, Any], action: Callable[[], Any]) -> dict:
    """调用面板方法，库的英文错误原样送出。"""

    try:
        panel = action()
    except Exception as exc:
        return failed(
            metadata.name,
            "HP_SHAPE_FAILED",
            english_message(exc, "Failed to reshape the HistoryPanel."),
            inputs_echo,
        )
    if type(panel).__name__ != "HistoryPanel":
        return failed(
            metadata.name,
            "HP_SHAPE_FAILED",
            "The reshape did not return a HistoryPanel.",
            inputs_echo,
        )
    return _panel_result(metadata, inputs_echo, panel)


def build_hp_slice_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.slice``。底层只调用 ``subpanel``。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.slice",
        version="0.1.0",
        summary="Slice a HistoryPanel by share, column, date, or row index.",
        inputs_schema={
            "shares": {"type": "string", "required": False},
            "htypes": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "index": {"type": "integer", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel slice"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.subpanel"],
        expected_artifact="A sliced HistoryPanel kept in memory for the next step.",
    )

    def handler(
        shares: Optional[str] = None,
        htypes: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        index: Any = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"shares": shares, "htypes": htypes, "start": start, "end": end, "index": index}
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        hdates = _slice_hdates(panel, start=start, end=end, index=index)
        if isinstance(hdates, str):
            return failed(metadata.name, "HP_SLICE_FAILED", hdates, inputs_echo)

        def action() -> Any:
            selected = {}
            if str(shares or "").strip():
                selected["shares"] = shares
            if str(htypes or "").strip():
                selected["htypes"] = htypes
            if hdates is not None:
                selected["hdates"] = hdates
            return panel.subpanel(**selected)

        return _run_panel(metadata, inputs_echo, action)

    return metadata, handler


def _slice_hdates(panel: Any, start: Any, end: Any, index: Any) -> Any:
    """日期闭区间或行号。都没给时返回 None，表示该轴全选。"""

    if index is not None and index != "":
        if isinstance(index, (list, tuple)):
            return list(index)
        return index
    start_key = _date_key(start) if str(start or "").strip() else ""
    end_key = _date_key(end) if str(end or "").strip() else ""
    if not start_key and not end_key:
        return None
    chosen = []
    for position, item in enumerate(panel.hdates):
        key = _date_key(item)
        if start_key and key < start_key:
            continue
        if end_key and key > end_key:
            continue
        chosen.append(position)
    if not chosen:
        return f"No rows in the requested slice from {start_key or '...'} to {end_key or '...'}."
    return chosen


def build_hp_drop_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.drop``。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.drop",
        version="0.1.0",
        summary="Drop shares or columns from a HistoryPanel.",
        inputs_schema={
            "htypes": {"type": "string", "required": False},
            "shares": {"type": "string", "required": False},
            "errors": {"type": "string", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel drop"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.drop"],
        expected_artifact="A HistoryPanel with the named shares or columns removed.",
    )

    def handler(
        htypes: Optional[str] = None,
        shares: Optional[str] = None,
        errors: str = "raise",
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htypes": htypes, "shares": shares, "errors": errors}
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        return _run_panel(
            metadata,
            inputs_echo,
            lambda: panel.drop(htypes=htypes, shares=shares, errors=errors or "raise"),
        )

    return metadata, handler


def build_hp_rename_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.rename``。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.rename",
        version="0.1.0",
        summary="Rename HistoryPanel shares or columns.",
        inputs_schema={
            "htypes": {"type": "object", "required": False},
            "shares": {"type": "object", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel rename"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.rename"],
        expected_artifact="A HistoryPanel with renamed labels.",
    )

    def handler(
        htypes: Optional[Dict[str, str]] = None,
        shares: Optional[Dict[str, str]] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htypes": htypes, "shares": shares}
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        return _run_panel(metadata, inputs_echo, lambda: panel.rename(htypes=htypes, shares=shares))

    return metadata, handler


def build_hp_fill_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.fill``。只做填补，且不改写上游面板。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.fill",
        version="0.1.0",
        summary="Fill missing HistoryPanel values with ffill, bfill, or a constant.",
        inputs_schema={
            "method": {
                "type": "string",
                "required": False,
                "enum": ["ffill", "bfill", "fillna"],
                "enum_strict": True,
            },
            "value": {"type": "number", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel fill"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.ffill", "qteasy.HistoryPanel.bfill", "qteasy.HistoryPanel.fillna"],
        expected_artifact="A filled HistoryPanel. The previous panel is left unchanged.",
    )

    def handler(
        method: str = "ffill",
        value: Optional[float] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        chosen = str(method or "ffill").strip().lower()
        inputs_echo = {"method": chosen, "value": value}
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        if chosen not in _FILL_METHODS:
            return failed(
                metadata.name,
                "HP_FILL_FAILED",
                "method must be one of ffill, bfill, fillna.",
                inputs_echo,
            )
        if chosen == "fillna" and value is None:
            return failed(
                metadata.name,
                "HP_FILL_VALUE_REQUIRED",
                "value is required when method is fillna.",
                inputs_echo,
            )

        def action() -> Any:
            if chosen == "ffill":
                return panel.ffill(inplace=False)
            if chosen == "bfill":
                return panel.bfill(inplace=False)
            return panel.fillna(value, inplace=False)

        return _run_panel(metadata, inputs_echo, action)

    return metadata, handler


def build_hp_dropna_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.dropna``。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.dropna",
        version="0.1.0",
        summary="Drop HistoryPanel slices that contain missing values.",
        inputs_schema={
            "axis": {"type": "string", "required": False},
            "how": {"type": "string", "required": False},
            "thresh": {"type": "integer", "required": False},
            "subset": {"type": "string", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel dropna"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.dropna"],
        expected_artifact="A HistoryPanel with empty slices removed.",
    )

    def handler(
        axis: str = "hdates",
        how: str = "any",
        thresh: Optional[int] = None,
        subset: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"axis": axis, "how": how, "thresh": thresh, "subset": subset}
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        return _run_panel(
            metadata,
            inputs_echo,
            lambda: panel.dropna(axis=axis or "hdates", how=how or "any", thresh=thresh, subset=subset),
        )

    return metadata, handler


def build_hp_resample_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.resample``。不设置回测频率。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.resample",
        version="0.1.0",
        summary="Resample a HistoryPanel along its dates. agg must cover every column.",
        inputs_schema={
            "rule": {"type": "string", "required": True},
            "agg": {"type": "object", "required": True},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel resample"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.resample"],
        expected_artifact="A HistoryPanel at the requested date frequency.",
    )

    def handler(
        rule: Optional[str] = None,
        agg: Optional[Dict[str, str]] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        mapped = _normalize_rule(str(rule or ""))
        inputs_echo = {"rule": mapped, "agg": agg}
        if not str(rule or "").strip():
            return failed(metadata.name, "HP_RESAMPLE_FAILED", "rule is required.", inputs_echo)
        if not isinstance(agg, dict) or not agg:
            return failed(
                metadata.name,
                "HP_RESAMPLE_FAILED",
                "agg is required and must cover every column.",
                inputs_echo,
            )
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        return _run_panel(metadata, inputs_echo, lambda: panel.resample(mapped, agg=dict(agg)))

    return metadata, handler


def build_hp_assign_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.assign``。只接受标量或可广播数组。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.assign",
        version="0.1.0",
        summary="Add one column from a scalar or a broadcastable numeric array.",
        inputs_schema={
            "column": {"type": "string", "required": True},
            "value": {"type": "number", "required": True},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel assign"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.assign"],
        expected_artifact="A HistoryPanel with one added or replaced column.",
    )

    def handler(
        column: Optional[str] = None,
        value: Any = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        name = str(column or "").strip()
        inputs_echo = {"column": name}
        if not name:
            return failed(metadata.name, "HP_ASSIGN_FAILED", "column is required.", inputs_echo)
        if isinstance(value, str) or callable(value):
            return failed(
                metadata.name,
                "HP_ASSIGN_FAILED",
                "value must be a number or a numeric array. Expressions and functions are not accepted.",
                inputs_echo,
            )
        panel = _require_panel(metadata, upstream_payload, inputs_echo)
        if isinstance(panel, dict):
            return panel
        array = _assign_value(value)
        if isinstance(array, str):
            return failed(metadata.name, "HP_ASSIGN_FAILED", array, inputs_echo)
        return _run_panel(
            metadata,
            inputs_echo,
            lambda: panel.assign(inplace=False, **{name: array}),
        )

    return metadata, handler


def _assign_value(value: Any) -> Any:
    """标量或数值数组。其它类型返回英文说明。"""

    if isinstance(value, bool) or value is None:
        return "value must be a number or a numeric array."
    if isinstance(value, (int, float, np.number)):
        return float(value)
    if isinstance(value, (list, tuple, np.ndarray)):
        try:
            array = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return "value must be a number or a numeric array."
        if array.dtype.kind not in {"f", "i", "u"}:
            return "value must be a number or a numeric array."
        return array
    return "value must be a number or a numeric array."


def build_hp_align_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.align``。两块面板的列名必须一致。"""

    metadata = SkillMetadata(
        name="qt.ai.hp.align",
        version="0.1.0",
        summary="Align two HistoryPanels on shares and dates.",
        inputs_schema={
            "join": {"type": "string", "required": False},
            "upstream_payload": {"type": "object", "required": False},
            "upstream_payloads": {"type": "array", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel align"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.align_to"],
        expected_artifact="Two aligned HistoryPanels with the same shares, dates, and columns.",
    )

    def handler(
        join: str = "inner",
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        how = str(join or "inner").strip().lower()
        inputs_echo = {"join": how}
        pair = _two_panels(metadata, upstream_payload, upstream_payloads, inputs_echo)
        if isinstance(pair, dict):
            return pair
        left, right = pair
        try:
            aligned_left, aligned_right = left.align_to(right, join=how)
        except Exception as exc:
            return failed(
                metadata.name,
                "HP_ALIGN_FAILED",
                english_message(exc, "Failed to align the two HistoryPanels."),
                inputs_echo,
            )
        return _panel_result(metadata, inputs_echo, aligned_left, other=aligned_right)

    return metadata, handler


def build_hp_join_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.join``。

    按标的、列、日期的并集合并。内核 ``HistoryPanel.join`` 在标的不同时
    仍会 ``NotImplementedError``，因此这里按该方法文档中的并集与左表优先
    语义组装新面板。
    """

    metadata = SkillMetadata(
        name="qt.ai.hp.join",
        version="0.1.0",
        summary="Join two HistoryPanels on the union of shares, columns, and dates.",
        inputs_schema={
            "upstream_payload": {"type": "object", "required": False},
            "upstream_payloads": {"type": "array", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel join"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.join"],
        expected_artifact="One HistoryPanel covering the union of both inputs.",
    )

    def handler(
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo: Dict[str, Any] = {}
        pair = _two_panels(metadata, upstream_payload, upstream_payloads, inputs_echo)
        if isinstance(pair, dict):
            return pair
        left, right = pair
        return _run_panel(metadata, inputs_echo, lambda: _union_join(left, right))

    return metadata, handler


def _union_join(left: Any, right: Any) -> Any:
    """按标的、列、日期的并集合并。重叠格子保留左表面板。

    ``HistoryPanel.join`` 在标的不同时仍是 ``NotImplementedError``。
    这里按该方法文档里的并集与左表优先语义组装新面板，不改内核。

    Parameters
    ----------
    left : HistoryPanel
        依赖顺序中的第一块面板。重叠处保留它的值。
    right : HistoryPanel
        依赖顺序中的第二块面板。

    Returns
    -------
    HistoryPanel
        并集面板。缺失格点为 NaN。
    """

    shares = sorted(set(left.shares) | set(right.shares))
    htypes = sorted(set(left.htypes) | set(right.htypes))
    hdates = sorted(set(left.hdates) | set(right.hdates))
    values = np.full((len(shares), len(hdates), len(htypes)), np.nan, dtype=float)
    _paint_join(values, right, shares, hdates, htypes)
    _paint_join(values, left, shares, hdates, htypes)
    return HistoryPanel(values=values, levels=shares, rows=hdates, columns=htypes)


def _paint_join(values: np.ndarray, panel: Any, shares: Sequence[Any], hdates: Sequence[Any], htypes: Sequence[Any]) -> None:
    """把一块面板画进并集数组。后画的格子覆盖先画的。"""

    share_at = {name: index for index, name in enumerate(shares)}
    date_at = {name: index for index, name in enumerate(hdates)}
    htype_at = {name: index for index, name in enumerate(htypes)}
    for share_index, share in enumerate(panel.shares):
        for date_index, date in enumerate(panel.hdates):
            for type_index, htype in enumerate(panel.htypes):
                values[share_at[share], date_at[date], htype_at[htype]] = float(
                    panel.values[share_index, date_index, type_index]
                )
