# coding=utf-8
# ======================================
# File: hp_study.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 组合、累计收益、归一化、alpha/beta 与绩效摘要原子。
# 默认值等于 HistoryPanel 公开签名。绩效摘要不是库方法。
# ======================================

"""HistoryPanel 组合与收益摘要技能。不注册 L2。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from ..slot_graph import code_spec, weights_spec
from .hp_panel import english_message, failed, panel_from_upstream
from .preview_rows import tabular_preview_rows

_PANEL_MISSING = "A HistoryPanel from the previous step is required."
_BENCHMARK_MISSING = "A benchmark price series is required."


def _meta(
    name: str,
    summary: str,
    inputs_schema: Dict[str, Any],
    entrypoint: str,
    artifact: str,
) -> SkillMetadata:
    """组装一条只读研究技能的元数据。

    Parameters
    ----------
    name : str
        注册名。
    summary : str
        给人读的一句说明。
    inputs_schema : dict
        确认卡使用的参数表。
    entrypoint : str
        对应的 qteasy 入口。绩效摘要没有库方法时传空串。
    artifact : str
        预期产物的一句说明。

    Returns
    -------
    SkillMetadata
        只读技能元数据。
    """

    entrypoints = [entrypoint] if entrypoint else []
    return SkillMetadata(
        name=name,
        version="0.1.0",
        summary=summary,
        inputs_schema=inputs_schema,
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel study"),
        required_capabilities=[],
        qteasy_entrypoints=entrypoints,
        expected_artifact=artifact,
    )


def _upstream_schema() -> Dict[str, Any]:
    """上游面板与掩码都由执行器注入。

    Returns
    -------
    dict
        ``upstream_payload`` 与 ``upstream_payloads`` 两个可选槽。
    """

    return {
        "upstream_payload": {"type": "object", "required": False},
        "upstream_payloads": {"type": "array", "required": False},
    }


def _upstream_list(upstream_payload: Any, upstream_payloads: Any) -> List[Dict[str, Any]]:
    """执行器会同时给出第一块和全部。有列表时以列表为准。

    Parameters
    ----------
    upstream_payload : Any
        第一块上游 payload。
    upstream_payloads : Any
        全部上游 payload。

    Returns
    -------
    list of dict
        可用的上游字典。
    """

    if isinstance(upstream_payloads, list) and upstream_payloads:
        return [item for item in upstream_payloads if isinstance(item, dict)]
    if isinstance(upstream_payload, dict):
        return [upstream_payload]
    return []


def _find_panel(payloads: Sequence[Dict[str, Any]]) -> Any:
    """取第一块上游面板。

    Parameters
    ----------
    payloads : sequence of dict
        上游 payload 列表。

    Returns
    -------
    HistoryPanel or None
        内存中的面板。
    """

    for item in payloads:
        panel = panel_from_upstream(item)
        if panel is not None:
            return panel
    return None


def _require_panel(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    upstream_payload: Any,
    upstream_payloads: Any,
) -> Any:
    """没有面板时返回失败字典。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    upstream_payload : Any
        第一块上游。
    upstream_payloads : Any
        全部上游。

    Returns
    -------
    HistoryPanel or dict
        面板，或失败的技能返回。
    """

    panel = _find_panel(_upstream_list(upstream_payload, upstream_payloads))
    if panel is None:
        return failed(metadata.name, "HP_PANEL_MISSING", _PANEL_MISSING, inputs_echo)
    return panel


def _chosen_mask(explicit: Any, payloads: Sequence[Dict[str, Any]]) -> Any:
    """显式掩码优先，否则用上游第一块布尔掩码。

    Parameters
    ----------
    explicit : Any
        调用方传入的掩码。
    payloads : sequence of dict
        上游 payload。

    Returns
    -------
    Any
        掩码；没有则 ``None``。
    """

    if explicit is not None:
        return explicit
    for item in payloads:
        mask = item.get("mask")
        if mask is not None:
            return mask
    return None


def _find_benchmark(benchmark: Any, payloads: Sequence[Dict[str, Any]]) -> Any:
    """参数里的价格序列优先，否则取上游 ``frame``。

    Parameters
    ----------
    benchmark : Any
        调用方传入的 Series 或 DataFrame。
    payloads : sequence of dict
        上游 payload。

    Returns
    -------
    Series, DataFrame, or None
        基准价格。字符串不会被当成面板里的标的名。
    """

    if isinstance(benchmark, (pd.Series, pd.DataFrame)):
        return benchmark
    for item in payloads:
        frame = item.get("frame")
        if isinstance(frame, (pd.Series, pd.DataFrame)):
            return frame
    return None


def _panel_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], panel: Any) -> dict:
    """成功的面板结果。完整面板留在 payload。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    panel : HistoryPanel
        新面板。

    Returns
    -------
    dict
        ``SkillResult.to_dict()``。
    """

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
        data_summary={
            "htypes": [str(name) for name in panel.htypes],
            "shares": [str(name) for name in panel.shares],
        },
        payload={"panel": panel, "preview_rows": tabular_preview_rows(panel)},
    )
    return result.to_dict()


def _frame_result(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    frame: pd.DataFrame,
    panel: Any,
) -> dict:
    """成功的表结果。原面板一并带回，供下一步继续用。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    frame : DataFrame
        摘要表。
    panel : HistoryPanel
        计算所用的原面板。

    Returns
    -------
    dict
        ``SkillResult.to_dict()``。
    """

    result = SkillResult(
        ok=True,
        skill_name=metadata.name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        metrics={"n_rows": int(len(frame.index)), "n_columns": int(len(frame.columns))},
        data_summary={"columns": [str(name) for name in frame.columns]},
        payload={
            "panel": panel,
            "frame": frame,
            "preview_rows": tabular_preview_rows(frame),
        },
    )
    return result.to_dict()


def _library_call(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    action: Callable[[], Any],
    code: str,
    fallback: str,
) -> Any:
    """调用库或本地算术。失败时把英文句子送出，不送回溯。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    action : callable
        无参调用。
    code : str
        失败错误码。
    fallback : str
        非英文异常时的替代句。

    Returns
    -------
    Any
        调用结果，或失败字典。
    """

    try:
        return action()
    except Exception as exc:
        return failed(metadata.name, code, english_message(exc, fallback), inputs_echo)


def _finish_panel(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    produced: Any,
    code: str,
    fallback: str,
) -> dict:
    """库返回面板则成功，否则英文失败。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    produced : Any
        库返回值，或已经是失败字典。
    code : str
        失败错误码。
    fallback : str
        返回类型不对时的英文句子。

    Returns
    -------
    dict
        技能返回。
    """

    if isinstance(produced, dict):
        return produced
    if type(produced).__name__ != "HistoryPanel":
        return failed(metadata.name, code, fallback, inputs_echo)
    return _panel_result(metadata, inputs_echo, produced)


def _performance_frame(panel: Any, htype: Any, periods_per_year: Any) -> pd.DataFrame:
    """从累计简单收益列算出末值、CAGR 和期数。

    Parameters
    ----------
    panel : HistoryPanel
        已含累计收益列的面板。
    htype : Any
        列名。只有一列时可以省略。
    periods_per_year : Any
        每年 bar 数。``None`` 时按 252。

    Returns
    -------
    DataFrame
        索引为标的，列为 ``cum_return_end``、``cagr``、``n_periods``。

    Raises
    ------
    ValueError
        列不明、期数非正、有效点不足，或累计收益不高于 -1。
    """

    columns = [str(name) for name in panel.htypes]
    chosen = htype
    if chosen in (None, ""):
        if len(columns) != 1:
            raise ValueError("htype is required when the panel has more than one column.")
        chosen = columns[0]
    if chosen not in columns:
        raise ValueError(f'htype "{chosen}" not found in htypes: {columns}')
    if periods_per_year is None:
        periods = 252.0
    else:
        try:
            periods = float(periods_per_year)
        except (TypeError, ValueError) as exc:
            raise ValueError("periods_per_year must be a positive number.") from exc
    if not np.isfinite(periods) or periods <= 0:
        raise ValueError("periods_per_year must be a positive number.")
    column = columns.index(str(chosen))
    ends: List[float] = []
    growth: List[float] = []
    counts: List[int] = []
    for share_index, _share in enumerate(list(panel.shares)):
        series = np.asarray(panel.values[share_index, :, column], dtype=float)
        finite = np.flatnonzero(np.isfinite(series))
        if finite.size < 2:
            raise ValueError("At least two finite values are required to compute CAGR.")
        n_periods = int(finite[-1] - finite[0])
        if n_periods <= 0:
            raise ValueError("At least two finite values are required to compute CAGR.")
        end = float(series[finite[-1]])
        if 1.0 + end <= 0.0:
            raise ValueError("Cumulative return must stay above -1 to compute CAGR.")
        years = n_periods / periods
        ends.append(end)
        growth.append(float((1.0 + end) ** (1.0 / years) - 1.0))
        counts.append(n_periods)
    return pd.DataFrame(
        {"cum_return_end": ends, "cagr": growth, "n_periods": counts},
        index=[str(name) for name in panel.shares],
    )


def build_hp_portfolio_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.portfolio``。默认等权，基准不参与聚合。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    schema = {
        "htypes": {"type": "string", "required": False},
        "mode": {"type": "string", "required": False},
        "weights": weights_spec(),
        "mask": {"type": "object", "required": False},
        "groups": {"type": "object", "required": False},
        "benchmark": code_spec(required=False),
        "benchmark_output": {"type": "string", "required": False},
        "new_share_name": {"type": "string", "required": False},
        "normalize_weights": {"type": "boolean", "required": False},
        "allow_ungrouped": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.portfolio",
        "Aggregate shares into a research portfolio.",
        schema,
        "qteasy.HistoryPanel.portfolio",
        "A new panel with one portfolio row. A benchmark is kept beside it, not inside the weights.",
    )

    def handler(
        htypes: Any = "close",
        mode: str = "equal",
        weights: Any = None,
        mask: Any = None,
        groups: Any = None,
        benchmark: Any = None,
        benchmark_output: str = "none",
        new_share_name: str = "PORTFOLIO",
        normalize_weights: bool = True,
        allow_ungrouped: str = "error",
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {
            "htypes": htypes,
            "mode": mode,
            "weights": weights,
            "groups": groups,
            "benchmark": benchmark,
            "benchmark_output": benchmark_output,
            "new_share_name": new_share_name,
            "normalize_weights": normalize_weights,
            "allow_ungrouped": allow_ungrouped,
        }
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        payloads = _upstream_list(upstream_payload, upstream_payloads)
        chosen = _chosen_mask(mask, payloads)

        def _run() -> Any:
            call: Dict[str, Any] = {
                "htypes": "close" if htypes in (None, "") else htypes,
                "mode": mode or "equal",
                "benchmark_output": benchmark_output or "none",
                "new_share_name": new_share_name or "PORTFOLIO",
                "normalize_weights": bool(normalize_weights),
                "allow_ungrouped": allow_ungrouped or "error",
            }
            if weights is not None:
                call["weights"] = np.asarray(weights, dtype=float)
            if groups:
                call["groups"] = groups
            if benchmark not in (None, ""):
                call["benchmark"] = str(benchmark)
            if chosen is not None:
                call["mask"] = np.asarray(chosen)
            return panel.portfolio(**call)

        produced = _library_call(
            metadata,
            inputs_echo,
            _run,
            "HP_PORTFOLIO_FAILED",
            "Failed to build the portfolio.",
        )
        return _finish_panel(
            metadata,
            inputs_echo,
            produced,
            "HP_PORTFOLIO_FAILED",
            "Failed to build the portfolio.",
        )

    return metadata, handler


def build_hp_cum_return_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.cum_return``。默认简单收益，列名交给库解析。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    schema = {
        "htypes": {"type": "string", "required": False},
        "method": {"type": "string", "required": False},
        "mask": {"type": "object", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.cum_return",
        "Cumulative return of price columns.",
        schema,
        "qteasy.HistoryPanel.cum_return",
        "A new panel of cumulative return columns.",
    )

    def handler(
        htypes: Any = None,
        method: str = "simple",
        mask: Any = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htypes": htypes, "method": method}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        chosen = _chosen_mask(mask, _upstream_list(upstream_payload, upstream_payloads))

        def _run() -> Any:
            call: Dict[str, Any] = {"method": method or "simple"}
            if htypes not in (None, ""):
                call["htypes"] = htypes
            if chosen is not None:
                call["mask"] = np.asarray(chosen)
            return panel.cum_return(**call)

        produced = _library_call(
            metadata,
            inputs_echo,
            _run,
            "HP_CUM_RETURN_FAILED",
            "Failed to compute cumulative return.",
        )
        return _finish_panel(
            metadata,
            inputs_echo,
            produced,
            "HP_CUM_RETURN_FAILED",
            "Failed to compute cumulative return.",
        )

    return metadata, handler


def build_hp_normalize_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.normalize``。默认以第一根为基准缩放到 1。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    schema = {
        "htypes": {"type": "string", "required": False},
        "base_index": {"type": "integer", "required": False},
        "mask": {"type": "object", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.normalize",
        "Scale price columns to 1 at a base bar.",
        schema,
        "qteasy.HistoryPanel.normalize",
        "A new panel of normalized columns.",
    )

    def handler(
        htypes: Any = None,
        base_index: int = 0,
        mask: Any = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htypes": htypes, "base_index": base_index}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        chosen = _chosen_mask(mask, _upstream_list(upstream_payload, upstream_payloads))

        def _run() -> Any:
            call: Dict[str, Any] = {"base_index": int(base_index)}
            if htypes not in (None, ""):
                call["htypes"] = htypes
            if chosen is not None:
                call["mask"] = np.asarray(chosen)
            return panel.normalize(**call)

        produced = _library_call(
            metadata,
            inputs_echo,
            _run,
            "HP_NORMALIZE_FAILED",
            "Failed to normalize the panel.",
        )
        return _finish_panel(
            metadata,
            inputs_echo,
            produced,
            "HP_NORMALIZE_FAILED",
            "Failed to normalize the panel.",
        )

    return metadata, handler


def build_hp_alpha_beta_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.alpha_beta``。基准来自价格序列或上游表。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    schema = {
        "price_htype": {"type": "string", "required": False},
        "method": {"type": "string", "required": False},
        "freq": {"type": "string", "required": False},
        "annualize": {"type": "boolean", "required": False},
        "benchmark": {"type": "object", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.alpha_beta",
        "Alpha and beta of each share against a benchmark price series.",
        schema,
        "qteasy.HistoryPanel.alpha_beta",
        "A table of alpha, beta, r2, and n_obs. The source panel stays available.",
    )

    def handler(
        benchmark: Any = None,
        price_htype: str = "close",
        method: str = "simple",
        freq: Optional[str] = None,
        annualize: bool = True,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {
            "price_htype": price_htype,
            "method": method,
            "freq": freq,
            "annualize": annualize,
        }
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        bench = _find_benchmark(benchmark, _upstream_list(upstream_payload, upstream_payloads))
        if bench is None:
            return failed(metadata.name, "HP_ALPHA_BETA_FAILED", _BENCHMARK_MISSING, inputs_echo)

        def _run() -> pd.DataFrame:
            call: Dict[str, Any] = {
                "benchmark": bench,
                "price_htype": price_htype or "close",
                "method": method or "simple",
                "annualize": bool(annualize),
            }
            if freq not in (None, ""):
                call["freq"] = freq
            frame = panel.alpha_beta(**call)
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("alpha_beta did not return a table.")
            return frame

        produced = _library_call(
            metadata,
            inputs_echo,
            _run,
            "HP_ALPHA_BETA_FAILED",
            "Failed to compute alpha and beta.",
        )
        if isinstance(produced, dict):
            return produced
        return _frame_result(metadata, inputs_echo, produced, panel)

    return metadata, handler


def build_hp_performance_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.performance``。从累计简单收益列算 CAGR。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。年数等于期数除以 ``periods_per_year``。
    """

    schema = {
        "htype": {"type": "string", "required": False},
        "periods_per_year": {"type": "integer", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.performance",
        "CAGR and ending cumulative return from one return column.",
        schema,
        "",
        "A summary table of cum_return_end, cagr, and n_periods. The source panel stays available.",
    )

    def handler(
        htype: Any = None,
        periods_per_year: Any = 252,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htype": htype, "periods_per_year": periods_per_year}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: _performance_frame(panel, htype, periods_per_year),
            "HP_PERFORMANCE_FAILED",
            "Failed to summarize cumulative return.",
        )
        if isinstance(produced, dict):
            return produced
        return _frame_result(metadata, inputs_echo, produced, panel)

    return metadata, handler
