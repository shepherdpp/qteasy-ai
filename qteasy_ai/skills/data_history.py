# coding=utf-8
# ======================================
# File: data_history.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：get_history_data 取历史列并产出 HistoryPanel。
# ======================================

"""历史列取数原子。不联网。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from ..slot_graph import asset_type_spec, code_spec, dtype_spec, freq_spec, window_bound_spec
from .hp_panel import english_message, failed
from .preview_rows import tabular_preview_rows


def build_data_history_skill(
    get_history_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.history``。

    Parameters
    ----------
    get_history_func : callable, optional
        注入 ``qteasy.get_history_data``。缺省时在调用时导入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。内部固定 ``as_data_frame=False``。
    """

    if get_history_func is None:
        import qteasy as qt

        get_history_func = qt.get_history_data

    metadata = SkillMetadata(
        name="qt.ai.data.history",
        version="0.1.0",
        summary="Read local history columns into a HistoryPanel via get_history_data.",
        inputs_schema={
            "htype_names": dtype_spec(required=True),
            "shares": code_spec(required=True),
            "start": window_bound_spec("start"),
            "end": window_bound_spec("end"),
            "freq": freq_spec(),
            "rows": {"type": "integer", "required": False},
            "asset_type": asset_type_spec(),
            "adj": {"type": "string", "required": False},
        },
        any_of=[["start", "end"]],
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly local history"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_history_data"],
        expected_artifact="A short preview of a HistoryPanel. The full panel stays in memory for the next step.",
    )

    def handler(
        htype_names: Optional[str] = None,
        shares: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: Optional[str] = None,
        rows: Optional[int] = None,
        asset_type: Optional[str] = None,
        adj: Optional[str] = None,
        **kwargs,
    ) -> dict:
        names = str(htype_names or "").strip()
        symbol = str(shares or "").strip()
        start_text = str(start or "").strip()
        end_text = str(end or "").strip()
        inputs_echo = {
            "htype_names": names,
            "shares": symbol,
            "start": start_text or None,
            "end": end_text or None,
            "freq": freq,
            "rows": rows,
            "asset_type": asset_type,
            "adj": adj,
        }
        if not names:
            return failed(
                metadata.name,
                "HISTORY_HTYPES_REQUIRED",
                "htype_names is required to read a history panel.",
                inputs_echo,
            )
        if not symbol:
            return failed(
                metadata.name,
                "HISTORY_SHARES_REQUIRED",
                "shares is required to read a history panel.",
                inputs_echo,
            )
        if not start_text and not end_text:
            return failed(
                metadata.name,
                "HISTORY_WINDOW_REQUIRED",
                "start or end is required. rows alone does not select a history window.",
                inputs_echo,
            )
        try:
            data = get_history_func(
                htype_names=names,
                shares=symbol,
                start=start_text or None,
                end=end_text or None,
                freq=freq,
                rows=rows,
                asset_type=asset_type,
                adj=adj,
                as_data_frame=False,
            )
        except Exception as exc:
            return failed(
                metadata.name,
                "HISTORY_FETCH_FAILED",
                english_message(exc, "Failed to read history data."),
                inputs_echo,
            )
        if type(data).__name__ != "HistoryPanel":
            return failed(
                metadata.name,
                "HISTORY_FETCH_FAILED",
                "get_history_data did not return a HistoryPanel.",
                inputs_echo,
            )
        if data.is_empty:
            return failed(
                metadata.name,
                "HISTORY_FETCH_FAILED",
                "No history data returned.",
                inputs_echo,
            )
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_rows": int(data.row_count), "n_shares": len(list(data.shares))},
            data_summary={"htypes": list(data.htypes), "shares": list(data.shares)},
            payload={"panel": data, "preview_rows": tabular_preview_rows(data)},
        )
        return result.to_dict()

    return metadata, handler
