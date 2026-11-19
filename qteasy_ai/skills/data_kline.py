# coding=utf-8
# ======================================
# File: data_kline.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# 只读技能：get_kline 取 OHLCV 面板，供后续 HistoryPanel 步骤使用。
# ======================================

"""K 线取数原子。不联网。"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from ..slot_graph import asset_type_spec, code_spec, date_field_spec, freq_spec, join_code_text
from .hp_panel import as_history_panel, english_message, failed
from .preview_rows import tabular_preview_rows


def build_data_kline_skill(
    get_kline_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.kline``。

    Parameters
    ----------
    get_kline_func : callable, optional
        注入 ``qteasy.get_kline``。缺省时在调用时导入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if get_kline_func is None:
        import qteasy as qt

        get_kline_func = qt.get_kline

    metadata = SkillMetadata(
        name="qt.ai.data.kline",
        version="0.1.0",
        summary="Read a local OHLCV HistoryPanel via get_kline.",
        inputs_schema={
            "shares": code_spec(required=True),
            "start": {
                **date_field_spec("start", required=False, constraint=""),
                "default_kind": "kernel_window",
            },
            "end": {
                **date_field_spec("end", required=False, constraint=""),
                "default_kind": "kernel_window",
            },
            "rows": {"type": "integer", "required": False},
            "freq": freq_spec(),
            "adj": {"type": "string", "required": False},
            "asset_type": asset_type_spec(),
            "as_panel": {"type": "boolean", "required": False},
            "b_days_only": {"type": "boolean", "required": False},
            "trade_time_only": {"type": "boolean", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly local kline"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_kline"],
        expected_artifact="A short preview of the OHLCV panel. The full panel stays in memory for the next step.",
    )

    def handler(
        shares: Any = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        rows: Optional[int] = None,
        freq: str = "d",
        adj: Optional[str] = None,
        asset_type: Optional[str] = None,
        as_panel: bool = True,
        b_days_only: Optional[bool] = None,
        trade_time_only: Optional[bool] = None,
        **kwargs,
    ) -> dict:
        freq_value = str(freq or "d")
        symbol = join_code_text(shares).strip()
        inputs_echo = {
            "shares": symbol,
            "start": start,
            "end": end,
            "rows": rows,
            "freq": freq_value,
            "adj": adj,
            "asset_type": asset_type,
            "as_panel": as_panel,
            "b_days_only": b_days_only,
            "trade_time_only": trade_time_only,
        }
        if not symbol:
            return failed(
                metadata.name,
                "KLINE_SHARES_REQUIRED",
                "shares is required to read a kline panel.",
                inputs_echo,
            )
        try:
            data = get_kline_func(
                shares=symbol,
                start=start,
                end=end,
                rows=rows,
                freq=freq_value,
                adj=adj,
                asset_type=asset_type,
                as_panel=True if as_panel is None else as_panel,
                b_days_only=b_days_only,
                trade_time_only=trade_time_only,
            )
            panel = as_history_panel(data, symbol)
            preview_source = data if isinstance(data, (pd.DataFrame, dict)) else panel
        except Exception as exc:
            return failed(
                metadata.name,
                "KLINE_FETCH_FAILED",
                english_message(exc, "Failed to read kline data."),
                inputs_echo,
            )
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_rows": int(panel.row_count), "n_shares": len(list(panel.shares))},
            data_summary={"htypes": list(panel.htypes), "shares": list(panel.shares)},
            payload={"panel": panel, "preview_rows": tabular_preview_rows(preview_source)},
        )
        return result.to_dict()

    return metadata, handler
