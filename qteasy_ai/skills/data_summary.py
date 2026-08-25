# coding=utf-8
# ======================================
# File: data_summary.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 阶段A/B0 只读技能：K线数据摘要
# （含交易天数与波动率）。
# ======================================

"""K线数据摘要只读技能。"""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id


def _normalize_freq(freq: Optional[str]) -> str:
    """规范化频率字符串。"""

    if not freq:
        return "D"
    return str(freq).upper()


def _kline_frame_to_panel(data: pd.DataFrame, shares: str, close_col: str):
    """将单标的 K 线 DataFrame 收成 HistoryPanel（仅 close 列）。"""

    from qteasy import HistoryPanel

    close = data[close_col].astype(float).to_numpy()
    values = close.reshape(1, -1, 1)
    return HistoryPanel(
        values,
        levels=[shares],
        rows=list(data.index),
        columns=["close"],
    )


def _compute_volatility_metrics(data: pd.DataFrame, shares: str, close_col: str) -> Tuple[float, float]:
    """经 HistoryPanel.returns 计算日波动率与年化波动率。

    Returns
    -------
    Tuple[float, float]
        ``(volatility_daily, volatility_annualized)``；有效收益不足 2 点时均为 NaN。
    """

    panel = _kline_frame_to_panel(data, shares=shares, close_col=close_col)
    ret_df = panel.returns(price_htype="close", method="simple", as_panel=False, dropna=False)
    series = ret_df.iloc[:, 0].dropna()
    if len(series) < 2:
        return float("nan"), float("nan")
    vol_daily = float(series.std(ddof=1))
    vol_annual = vol_daily * float(np.sqrt(252.0))
    return vol_daily, vol_annual


def build_data_summary_skill(
    get_kline_func: Callable[..., pd.DataFrame] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 K 线摘要技能。"""

    if get_kline_func is None:
        import qteasy as qt

        get_kline_func = qt.get_kline

    metadata = SkillMetadata(
        name="qt.ai.data.summary_kline",
        version="0.1.5",
        summary="Summarize kline data including trading days and volatility.",
        inputs_schema={
            "shares": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.get_kline", "qteasy.HistoryPanel.returns"],
    )

    def handler(
        shares: str = "000300.SH",
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: str = "D",
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        freq_value = _normalize_freq(freq)
        inputs_echo = {
            "shares": shares,
            "start": start,
            "end": end,
            "freq": freq_value,
            **kwargs,
        }
        try:
            data = get_kline_func(
                shares=shares,
                start=start,
                end=end,
                freq=freq_value,
                as_panel=False,
            )
            if isinstance(data, dict):
                if not data:
                    raise ValueError("No data returned.")
                first_key = sorted(data.keys())[0]
                data = data[first_key]
            if data is None or data.empty:
                raise ValueError("No data returned.")
            close_col = "close" if "close" in data.columns else data.columns[0]
            close_values = data[close_col].astype(float)
            n_rows = int(len(data))
            vol_daily, vol_annual = _compute_volatility_metrics(
                data, shares=shares, close_col=str(close_col)
            )
            metrics = {
                "n_rows": n_rows,
                "n_trading_days": n_rows,
                "n_cols": int(len(data.columns)),
                "close_min": float(np.nanmin(close_values.values)),
                "close_max": float(np.nanmax(close_values.values)),
                "nan_ratio_close": float(np.isnan(close_values.values).mean()),
                "volatility_daily": vol_daily,
                "volatility_annualized": vol_annual,
            }
            data_summary: Dict[str, object] = {
                "columns": [str(col) for col in data.columns],
                "index_start": str(data.index.min()),
                "index_end": str(data.index.max()),
            }
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary=data_summary,
                payload={"preview": data.head(5).to_dict(orient="records")},
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="KLINE_SUMMARY_FAILED",
                    message=f"Failed to summarize kline data: {exc}",
                ),
            )
        return {
            "ok": result.ok,
            "skill_name": result.skill_name,
            "run_id": result.run_id,
            "inputs_echo": result.inputs_echo,
            "metrics": result.metrics,
            "data_summary": result.data_summary,
            "payload": result.payload,
            "warnings": result.warnings,
            "error": None if result.error is None else result.error.__dict__,
            "artifacts": result.artifacts,
        }

    return metadata, handler
