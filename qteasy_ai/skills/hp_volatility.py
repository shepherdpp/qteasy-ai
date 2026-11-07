# coding=utf-8
# ======================================
# File: hp_volatility.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# 只读技能：HistoryPanel.volatility 的滚动波动率。
# ======================================

"""滚动波动率原子。参数默认值等于库默认。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed, panel_from_upstream
from .preview_rows import tabular_preview_rows


def _last_value(result: Any) -> float:
    """取结果最后一根 bar 的波动率。"""

    if isinstance(result, pd.DataFrame):
        if result.empty:
            return float("nan")
        return float(result.iloc[-1, 0])
    if isinstance(result, pd.Series):
        if result.empty:
            return float("nan")
        return float(result.iloc[-1])
    values = getattr(result, "values", None)
    if values is None:
        return float("nan")
    flat = np.asarray(values, dtype=float)
    if flat.size == 0:
        return float("nan")
    return float(flat.reshape(-1)[-1])


def build_hp_volatility_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.volatility``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    metadata = SkillMetadata(
        name="qt.ai.hp.volatility",
        version="0.1.0",
        summary="Rolling volatility of an upstream HistoryPanel.",
        inputs_schema={
            "window": {"type": "integer", "required": False},
            "price_htype": {"type": "string", "required": False},
            "method": {"type": "string", "required": False},
            "annualize": {"type": "boolean", "required": False},
            "periods_per_year": {"type": "integer", "required": False},
            "as_panel": {"type": "boolean", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(description="readonly rolling volatility"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.volatility"],
        expected_artifact="A table of rolling volatility. The last value is in metrics.last.",
    )

    def handler(
        window: int = 20,
        price_htype: str = "close",
        method: str = "simple",
        annualize: bool = True,
        periods_per_year: Optional[int] = None,
        as_panel: bool = False,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {
            "window": window,
            "price_htype": price_htype,
            "method": method,
            "annualize": annualize,
            "periods_per_year": periods_per_year,
            "as_panel": as_panel,
        }
        panel = panel_from_upstream(upstream_payload)
        if panel is None:
            return failed(
                metadata.name,
                "HP_PANEL_MISSING",
                "A HistoryPanel from the previous step is required.",
                inputs_echo,
            )
        try:
            call = {
                "window": int(window),
                "price_htype": str(price_htype or "close"),
                "method": str(method or "simple"),
                "annualize": bool(annualize),
                "as_panel": bool(as_panel),
            }
            if periods_per_year is not None:
                call["periods_per_year"] = int(periods_per_year)
            computed = panel.volatility(**call)
            last = _last_value(computed)
        except Exception as exc:
            return failed(
                metadata.name,
                "HP_VOLATILITY_FAILED",
                english_message(exc, "Failed to compute rolling volatility."),
                inputs_echo,
            )
        payload: Dict[str, Any] = {"preview_rows": tabular_preview_rows(computed)}
        if type(computed).__name__ == "HistoryPanel":
            payload["panel"] = computed
        elif isinstance(computed, (pd.DataFrame, pd.Series)):
            payload["frame"] = computed
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"last": last, "window": int(window)},
            data_summary={"price_htype": str(price_htype or "close"), "annualize": bool(annualize)},
            payload=payload,
        )
        return result.to_dict()

    return metadata, handler
