# coding=utf-8
# ======================================
# File: hp_indicator.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 面板指标、蜡烛形态与研究预设原子。
# 五个常用指标走 kline 追加列，其余走 apply_ta。
# ======================================

"""HistoryPanel 指标与形态技能。不按指标拆技能，也不执行任意 Python。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed, panel_from_upstream
from .preview_rows import tabular_preview_rows

_PANEL_MISSING = "A HistoryPanel from the previous step is required."
_KLINE_PARAMS = {
    "sma": ("window", "price_htype", "new_htype", "inplace"),
    "ema": ("span", "price_htype", "new_htype", "inplace"),
    "bbands": ("window", "price_htype", "nbdev_up", "nbdev_dn", "ma_type", "suffix", "inplace"),
    "macd": ("price_htype", "fastperiod", "slowperiod", "signalperiod", "suffix", "inplace"),
    "kdj": ("price_htype", "fastk_period", "slowk_period", "slowd_period", "suffix", "inplace"),
}
_PRICE_HTYPES = ("open", "high", "low", "close")


def _meta(
    name: str,
    summary: str,
    inputs_schema: Dict[str, Any],
    entrypoint: str,
    artifact: str,
) -> SkillMetadata:
    """组装一条只读指标技能的元数据。

    Parameters
    ----------
    name : str
        注册名。
    summary : str
        给人读的一句说明。
    inputs_schema : dict
        确认卡使用的参数表。
    entrypoint : str
        对应的 qteasy 入口。
    artifact : str
        预期产物的一句说明。

    Returns
    -------
    SkillMetadata
        只读技能元数据。
    """

    return SkillMetadata(
        name=name,
        version="0.1.0",
        summary=summary,
        inputs_schema=inputs_schema,
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel indicator"),
        required_capabilities=[],
        qteasy_entrypoints=[entrypoint],
        expected_artifact=artifact,
    )


def _upstream_schema() -> Dict[str, Any]:
    """上游面板由执行器注入。

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
        找到的面板。没有则是 None。
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
        第一块上游 payload。
    upstream_payloads : Any
        全部上游 payload。

    Returns
    -------
    HistoryPanel or dict
        面板，或一次失败返回。
    """

    panel = _find_panel(_upstream_list(upstream_payload, upstream_payloads))
    if panel is None:
        return failed(metadata.name, "HP_PANEL_MISSING", _PANEL_MISSING, inputs_echo)
    return panel


def _panel_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], panel: Any) -> dict:
    """成功的面板结果。完整面板留在 payload。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    panel : HistoryPanel
        追加列后的面板。

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


def _frame_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], frame: pd.DataFrame) -> dict:
    """成功的表结果。DataFrame 留在内存，预览另给。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    frame : DataFrame
        形态信号表。

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
        payload={"frame": frame, "preview_rows": tabular_preview_rows(frame)},
    )
    return result.to_dict()


def _call(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    action: Callable[[], Any],
    code: str,
    fallback: str,
    unavailable: str,
) -> Any:
    """调用库。环境缺函数时点名，其它失败只留英文句子。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    action : callable
        实际库调用。
    code : str
        失败码。
    fallback : str
        非英文异常时的替代句。
    unavailable : str
        ``NameError`` 或 ``ImportError`` 时点名的英文句子。

    Returns
    -------
    Any
        库的返回值，或一次失败字典。
    """

    try:
        return action()
    except (NameError, ImportError):
        return failed(metadata.name, code, unavailable, inputs_echo)
    except Exception as exc:
        return failed(metadata.name, code, english_message(exc, fallback), inputs_echo)


def _object_kwargs(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    code: str,
    kwargs: Any,
) -> Tuple[Optional[Dict[str, Any]], Optional[dict]]:
    """``kwargs`` 必须是对象。省略当成空对象。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    code : str
        失败码。
    kwargs : Any
        调用方传入的额外参数。

    Returns
    -------
    tuple
        ``(参数字典, None)``，或 ``(None, 失败字典)``。
    """

    if kwargs is None:
        return {}, None
    if not isinstance(kwargs, dict):
        return None, failed(metadata.name, code, "kwargs must be an object.", inputs_echo)
    return dict(kwargs), None


def _finish(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    produced: Any,
    code: str,
    fallback: str,
    *,
    as_panel: bool,
) -> dict:
    """按 ``as_panel`` 收成面板或表。失败字典原样返回。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    produced : Any
        库返回值或失败字典。
    code : str
        类型不对时的失败码。
    fallback : str
        类型不对时的英文句子。
    as_panel : bool
        为真时要求 HistoryPanel，否则要求 DataFrame。

    Returns
    -------
    dict
        技能返回。
    """

    if isinstance(produced, dict):
        return produced
    if as_panel:
        if type(produced).__name__ != "HistoryPanel":
            return failed(metadata.name, code, fallback, inputs_echo)
        return _panel_result(metadata, inputs_echo, produced)
    if not isinstance(produced, pd.DataFrame):
        return failed(metadata.name, code, fallback, inputs_echo)
    return _frame_result(metadata, inputs_echo, produced)


def build_hp_indicator_skill() -> Tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.indicator``。五个 kline 名字追加列，其余走 ``apply_ta``。

    Parameters
    ----------
    无

    Returns
    -------
    tuple
        元数据与处理函数。
    """

    schema = {
        "func_name": {"type": "string", "required": True},
        "htype": {"type": "string", "required": False, "default": "close"},
        "shares": {"type": "array", "required": False},
        "as_panel": {"type": "boolean", "required": False, "default": True},
        "kwargs": {"type": "object", "required": False, "default": {}},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.indicator",
        "Append one technical indicator to a panel.",
        schema,
        "qteasy.HistoryPanel.kline / qteasy.HistoryPanel.apply_ta",
        "The same HistoryPanel plus the indicator columns, or a table when as_panel is false.",
    )

    def handler(
        func_name: Optional[str] = None,
        htype: str = "close",
        shares: Any = None,
        as_panel: bool = True,
        kwargs: Optional[Dict[str, Any]] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **extra: Any,
    ) -> dict:
        del extra
        inputs_echo = {
            "func_name": func_name,
            "htype": htype,
            "shares": shares,
            "as_panel": as_panel,
            "kwargs": kwargs or {},
        }
        name = str(func_name or "").strip()
        if not name:
            return failed(metadata.name, "HP_INDICATOR_FAILED", "func_name is required.", inputs_echo)
        call_kwargs, rejected = _object_kwargs(metadata, inputs_echo, "HP_INDICATOR_FAILED", kwargs)
        if rejected is not None:
            return rejected
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        if name in _KLINE_PARAMS:
            return _run_kline(metadata, inputs_echo, panel, name, htype, call_kwargs)
        if name.lower().startswith("cdl"):
            return failed(
                metadata.name,
                "HP_INDICATOR_FAILED",
                f'Candle pattern "{name}" is computed by hp.candle_pattern, not hp.indicator.',
                inputs_echo,
            )
        return _run_apply_ta(metadata, inputs_echo, panel, name, htype, shares, bool(as_panel), call_kwargs)

    return metadata, handler


def _run_kline(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    panel: Any,
    func_name: str,
    htype: str,
    call_kwargs: Dict[str, Any],
) -> dict:
    """用 kline 方法追加列。不接受的参数名直接英文拒绝。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    panel : HistoryPanel
        上游面板。
    func_name : str
        ``sma`` / ``ema`` / ``macd`` / ``bbands`` / ``kdj`` 之一。
    htype : str
        未写 ``price_htype`` 时使用的价格列。
    call_kwargs : dict
        该 kline 方法的公开参数。

    Returns
    -------
    dict
        新面板，或英文失败。
    """

    allowed = set(_KLINE_PARAMS[func_name])
    unknown = [key for key in call_kwargs if key not in allowed]
    if unknown:
        rejected = unknown[0]
        return failed(
            metadata.name,
            "HP_INDICATOR_FAILED",
            f'Parameter "{rejected}" is not accepted by {func_name}.',
            inputs_echo,
        )
    params = dict(call_kwargs)
    if "price_htype" not in params:
        params["price_htype"] = htype or "close"
    params.setdefault("inplace", False)
    produced = _call(
        metadata,
        inputs_echo,
        lambda: getattr(panel.kline, func_name)(**params),
        "HP_INDICATOR_FAILED",
        f'Failed to compute indicator "{func_name}".',
        f'Technical indicator "{func_name}" is not available in this environment.',
    )
    return _finish(
        metadata,
        inputs_echo,
        produced,
        "HP_INDICATOR_FAILED",
        f'Indicator "{func_name}" did not return a HistoryPanel.',
        as_panel=True,
    )


def _run_apply_ta(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    panel: Any,
    func_name: str,
    htype: str,
    shares: Any,
    as_panel: bool,
    call_kwargs: Dict[str, Any],
) -> dict:
    """把 ``kwargs`` 原样交给 ``HistoryPanel.apply_ta``。

    Parameters
    ----------
    metadata : SkillMetadata
        当前技能。
    inputs_echo : dict
        回显入参。
    panel : HistoryPanel
        上游面板。
    func_name : str
        ``qteasy.tafuncs`` 中的函数名。
    htype : str
        输入列，默认 ``close``。
    shares : Any
        限定标的。省略则用全部。
    as_panel : bool
        为真时返回面板，否则返回表。
    call_kwargs : dict
        指标函数自己的参数。

    Returns
    -------
    dict
        面板或表，或英文失败。
    """

    ta_kwargs: Dict[str, Any] = {
        "func_name": func_name,
        "htype": htype or "close",
        "as_panel": as_panel,
    }
    if shares is not None:
        ta_kwargs["shares"] = shares
    produced = _call(
        metadata,
        inputs_echo,
        lambda: panel.apply_ta(**ta_kwargs, **call_kwargs),
        "HP_INDICATOR_FAILED",
        f'Failed to compute indicator "{func_name}".',
        f'Technical indicator "{func_name}" is not available in this environment.',
    )
    return _finish(
        metadata,
        inputs_echo,
        produced,
        "HP_INDICATOR_FAILED",
        f'Indicator "{func_name}" did not return a result.',
        as_panel=as_panel,
    )


def build_hp_candle_pattern_skill() -> Tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.candle_pattern``。一个技能覆盖全部 ``cdl*``。

    Parameters
    ----------
    无

    Returns
    -------
    tuple
        元数据与处理函数。
    """

    schema = {
        "name": {"type": "string", "required": True},
        "price_htypes": {
            "type": "array",
            "required": False,
            "default": list(_PRICE_HTYPES),
        },
        "as_panel": {"type": "boolean", "required": False, "default": False},
        "kwargs": {"type": "object", "required": False, "default": {}},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.candle_pattern",
        "Detect one candlestick pattern.",
        schema,
        "qteasy.HistoryPanel.candle_pattern",
        "A signal table, or a one-column HistoryPanel when as_panel is true.",
    )

    def handler(
        name: Optional[str] = None,
        price_htypes: Optional[Sequence[str]] = None,
        as_panel: bool = False,
        kwargs: Optional[Dict[str, Any]] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **extra: Any,
    ) -> dict:
        del extra
        chosen = list(price_htypes) if price_htypes is not None else list(_PRICE_HTYPES)
        inputs_echo = {
            "name": name,
            "price_htypes": chosen,
            "as_panel": as_panel,
            "kwargs": kwargs or {},
        }
        pattern = str(name or "").strip()
        if not pattern:
            return failed(metadata.name, "HP_CANDLE_FAILED", "name is required.", inputs_echo)
        if not pattern.lower().startswith("cdl"):
            return failed(
                metadata.name,
                "HP_CANDLE_FAILED",
                f'name must be a cdl* function in qteasy.tafuncs, got "{pattern}".',
                inputs_echo,
            )
        call_kwargs, rejected = _object_kwargs(metadata, inputs_echo, "HP_CANDLE_FAILED", kwargs)
        if rejected is not None:
            return rejected
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _call(
            metadata,
            inputs_echo,
            lambda: panel.candle_pattern(
                pattern,
                price_htypes=tuple(chosen),
                as_panel=bool(as_panel),
                **call_kwargs,
            ),
            "HP_CANDLE_FAILED",
            f'Failed to compute candle pattern "{pattern}".',
            f'Candle pattern "{pattern}" is not available in this environment.',
        )
        return _finish(
            metadata,
            inputs_echo,
            produced,
            "HP_CANDLE_FAILED",
            f'Candle pattern "{pattern}" did not return a result.',
            as_panel=bool(as_panel),
        )

    return metadata, handler


def build_hp_research_preset_skill() -> Tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.research_preset``。库里现成的预设只有 ``ohlcv_macd_ma``。

    Parameters
    ----------
    无

    Returns
    -------
    tuple
        元数据与处理函数。
    """

    schema = {
        "name": {"type": "string", "required": True},
        "inplace": {"type": "boolean", "required": False, "default": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.research_preset",
        "Append the built-in OHLCV, MACD, and SMA columns.",
        schema,
        "qteasy.HistoryPanel.research_preset",
        "The same HistoryPanel plus the preset indicator columns.",
    )

    def handler(
        name: Optional[str] = None,
        inplace: bool = False,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **extra: Any,
    ) -> dict:
        del extra
        inputs_echo = {"name": name, "inplace": inplace}
        preset = str(name or "").strip()
        if not preset:
            return failed(metadata.name, "HP_PRESET_FAILED", "name is required.", inputs_echo)
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _call(
            metadata,
            inputs_echo,
            lambda: panel.research_preset(preset, inplace=bool(inplace)),
            "HP_PRESET_FAILED",
            f'Failed to build research preset "{preset}".',
            f'Research preset "{preset}" is not available in this environment.',
        )
        return _finish(
            metadata,
            inputs_echo,
            produced,
            "HP_PRESET_FAILED",
            f'Research preset "{preset}" did not return a HistoryPanel.',
            as_panel=True,
        )

    return metadata, handler
